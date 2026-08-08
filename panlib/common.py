"""
Shared configuration, process and output boundaries for the panlib commands.

The module deliberately keeps all configuration portable: values from the
process environment win over a repository ``.env`` file, which wins over the
safe defaults below.  ``Settings`` is immutable so a command cannot silently
change its cloud root halfway through a run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

# The repository root remains discoverable from every bin/ entry point.
SKILL_ROOT = Path(__file__).resolve().parent.parent

# Error codes
NETWORK = "NETWORK"
PARSE = "PARSE"
AUTH = "AUTH"
NOT_FOUND = "NOT_FOUND"
PERMISSION = "PERMISSION"
INVALID_ARG = "INVALID_ARG"
INTERNAL = "INTERNAL"

_DEFAULTS: dict[str, str] = {
    "BDPAN_BASE": "/apps/bdpan",
    "BDPAN_LIB": "片库",
    "BDPAN_BIN": "bdpan",
    "SEEDHUB_CLI": "vendor/seedhub-cli/seedhub.py",
    "VENV_PYTHON": ".venv/bin/python",
    "LOG_LEVEL": "info",
    "USE_KNOWN_IMDB_TABLE": "true",
    "NETWORK_TIMEOUT": "30",
    "BDPAN_TIMEOUT": "600",
}


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved process settings, loaded once and safe to share read-only."""

    venv_python: Path
    seedhub_cli: Path
    bdpan_bin: Path
    bdpan_base: str
    bdpan_lib: str
    network_timeout: int
    bdpan_timeout: int
    log_level: str = "info"
    use_known_imdb_table: bool = True


def _positive_int(value: str, key: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return parsed


def _parse_bool(value: str, key: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be true or false")


def _resolve_repo_path(value: str, key: str) -> Path:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    path = Path(value).expanduser()
    return path if path.is_absolute() else SKILL_ROOT / path


def _resolve_bdpan_bin(value: str) -> Path:
    value = str(value).strip()
    if not value:
        raise ValueError("BDPAN_BIN must not be empty")
    # A configured path/name is authoritative.  With no explicit value the
    # default is ``bdpan`` and is resolved through PATH when available.
    found = shutil.which(value)
    if found:
        return Path(found)
    return Path(value)


def _setting_value(
    key: str,
    dotenv: Mapping[str, str],
    environ: Mapping[str, str],
) -> str:
    if key in environ:
        return str(environ[key]).strip()
    if key in dotenv:
        return str(dotenv[key]).strip()
    return _DEFAULTS[key]


def load_settings(
    path: Path | str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Load immutable settings with environment > ``.env`` > defaults.

    ``path`` and ``environ`` are explicit seams for tests and embedding.  The
    normal command path reads only the repository-local ``.env`` if present.
    """

    env_file = Path(path) if path is not None else SKILL_ROOT / ".env"
    dotenv = load_env_file(env_file)
    source_env = os.environ if environ is None else environ

    base = _setting_value("BDPAN_BASE", dotenv, source_env)
    lib = _setting_value("BDPAN_LIB", dotenv, source_env)
    if not base or not lib:
        raise ValueError("BDPAN_BASE and BDPAN_LIB must not be empty")
    # Validate the base early, before any write-capable caller can use it.
    validate_cloud_path(base, base)
    _validate_cloud_component(lib)

    return Settings(
        venv_python=_resolve_repo_path(
            _setting_value("VENV_PYTHON", dotenv, source_env), "VENV_PYTHON"
        ),
        seedhub_cli=_resolve_repo_path(
            _setting_value("SEEDHUB_CLI", dotenv, source_env), "SEEDHUB_CLI"
        ),
        bdpan_bin=_resolve_bdpan_bin(
            _setting_value("BDPAN_BIN", dotenv, source_env)
        ),
        bdpan_base=base,
        bdpan_lib=lib,
        network_timeout=_positive_int(
            _setting_value("NETWORK_TIMEOUT", dotenv, source_env), "NETWORK_TIMEOUT"
        ),
        bdpan_timeout=_positive_int(
            _setting_value("BDPAN_TIMEOUT", dotenv, source_env), "BDPAN_TIMEOUT"
        ),
        log_level=_setting_value("LOG_LEVEL", dotenv, source_env).lower() or "info",
        use_known_imdb_table=_parse_bool(
            _setting_value("USE_KNOWN_IMDB_TABLE", dotenv, source_env),
            "USE_KNOWN_IMDB_TABLE",
        ),
    )


def _validate_cloud_component(component: str) -> None:
    if not isinstance(component, str) or not component or not component.strip():
        raise ValueError("cloud path components must not be empty")
    if component in {".", ".."} or "/" in component or "\\" in component:
        raise ValueError("cloud path component contains traversal or separator")
    if any(ord(char) < 32 or ord(char) == 127 for char in component):
        raise ValueError("cloud path component contains a control character")
    if any(char in component for char in ':*?"<>|'):
        raise ValueError("cloud path component contains an illegal character")


def validate_cloud_path(path: str | Path, base: str | Path | None = None) -> str:
    """Return a canonical POSIX cloud path only when it stays under ``base``."""

    raw_path = str(path)
    raw_base = str(SETTINGS.bdpan_base if base is None else base)
    if not raw_path or not raw_base:
        raise ValueError("cloud path and base must not be empty")
    if "\\" in raw_path or "\\" in raw_base:
        raise ValueError("cloud paths must use POSIX separators")
    # PurePosixPath intentionally folds repeated and trailing separators.  Do
    # this raw check first so an empty component cannot bypass containment.
    for raw_value in (raw_path, raw_base):
        components = raw_value[1:].split("/") if raw_value.startswith("/") else raw_value.split("/")
        if any(component == "" for component in components):
            raise ValueError("cloud paths must not contain empty components")
    path_obj = PurePosixPath(raw_path)
    base_obj = PurePosixPath(raw_base)
    if not path_obj.is_absolute() or not base_obj.is_absolute():
        raise ValueError("cloud paths must be absolute")
    if any(part in {".", ".."} for part in path_obj.parts + base_obj.parts):
        raise ValueError("cloud path traversal is not allowed")
    for part in path_obj.parts[1:] + base_obj.parts[1:]:
        _validate_cloud_component(part)
    try:
        path_obj.relative_to(base_obj)
    except ValueError as exc:
        raise ValueError("cloud path escapes BDPAN_BASE") from exc
    return str(path_obj)


def is_within_cloud_base(path: str | Path, base: str | Path | None = None) -> bool:
    try:
        validate_cloud_path(path, base)
    except (TypeError, ValueError):
        return False
    return True


def safe_cloud_join(base: str | Path, *parts: str | Path) -> str:
    """Join cloud path components while rejecting traversal and bad names."""

    base_value = validate_cloud_path(base, base)
    pieces = [base_value.rstrip("/")]
    for raw_part in parts:
        value = str(raw_part)
        if not value or value.startswith("/") or value.endswith("/"):
            raise ValueError("cloud path components must be non-empty and relative")
        if "\\" in value:
            raise ValueError("cloud paths must use POSIX separators")
        segments = value.split("/")
        if any(not segment for segment in segments):
            raise ValueError("cloud path components must not be empty")
        for segment in segments:
            _validate_cloud_component(segment)
        pieces.extend(segments)
    return validate_cloud_path("/".join(pieces), base_value)


# Readable aliases for callers that prefer a verb-oriented name.
join_cloud_path = safe_cloud_join
cloud_path = safe_cloud_join


_SENSITIVE_FIELD_PATTERN = (
    r"(?:pwd|password|passcode|token|"
    r"(?:access|refresh|session|id|api|auth|oauth)[_-]?token|"
    r"auth(?:entication)?(?:[_-]?(?:code|token|header))?|"
    r"authorization(?:[_-]?(?:code|token|header))?|"
    r"(?:client|api)[_-]?secret|api[_-]?key|secret|cookie|bduss|code)"
)
_QUERY_SECRET_RE = re.compile(
    rf"(?i)([?&]{_SENSITIVE_FIELD_PATTERN}=)([^&#\s]+)"
)
_KEY_VALUE_SECRET_RE = re.compile(
    r"(?i)(\b"
    + _SENSITIVE_FIELD_PATTERN
    + r"\b\s*[\"']?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,&;}]+(?:\s+[^\s,&;}]+)?)"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)(\bAuthorization\s*:\s*)([^\r\n]+)"
)
_UNIX_HOME_RE = re.compile(r"(?<![\w])/(?:Users|home)/[^/\s]+(?:/[^\s]*)?")
_WINDOWS_HOME_RE = re.compile(r"(?i)(?<![\w])(?:[A-Z]:)?[\\/]Users[\\/][^\\/\s]+(?:[\\/][^\s]*)?")
_SENSITIVE_FIELD_KEYS = {
    "pwd",
    "password",
    "token",
    "accesstoken",
    "refreshtoken",
    "auth",
    "authcode",
    "authorization",
    "authorizationcode",
    "clientsecret",
    "apikey",
    "code",
}


def _is_sensitive_field_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    if normalized in _SENSITIVE_FIELD_KEYS:
        return True
    parts = normalized.split("_")
    if not parts:
        return False
    # Treat explicit token/auth/secret families as sensitive while leaving
    # ordinary fields such as ``token_count`` untouched.
    if parts[-1] in {"token", "auth", "authorization", "secret", "cookie", "bduss"}:
        return parts[:-1] != ["count"]
    return normalized in {
        "auth_code",
        "authorization_code",
        "authorization_header",
        "client_secret",
        "api_secret",
        "access_token",
        "refresh_token",
        "session_token",
        "id_token",
        "api_token",
        "oauth_token",
        "auth_token",
        "api_key",
    }


def redact_text(value: Any) -> str:
    """Redact credentials, authorization values and personal home paths."""

    text = str(value)
    text = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", text)
    text = _KEY_VALUE_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = _UNIX_HOME_RE.sub("/[REDACTED]/[REDACTED]", text)
    text = _WINDOWS_HOME_RE.sub("[REDACTED]", text)
    return text


def redact_value(value: Any) -> Any:
    """Recursively redact JSON-like values without changing scalar types."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        return redact_text(value.decode("utf-8", errors="replace"))
    if isinstance(value, Mapping):
        safe_mapping: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_sensitive_field_key(key):
                safe_mapping[key] = "[REDACTED]"
            else:
                safe_mapping[key] = redact_value(item)
        return safe_mapping
    if isinstance(value, (list, tuple, set)):
        return [redact_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, os.PathLike):
        return redact_text(os.fspath(value))
    # ``json.dumps(..., default=str)`` would otherwise expose a Path or a
    # custom object verbatim, so make the fallback pass through the same
    # redaction pipeline.
    return redact_text(value)


redact_json = redact_value


redact = redact_text
sanitize_log = redact_text


def emit_success(data: Any, meta: dict | None = None) -> None:
    """Print success JSON to stdout and exit 0."""

    payload: dict[str, Any] = {"data": data}
    if meta is not None:
        payload["meta"] = meta
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0)


def emit_error(code: str, message: str, details: Any = None) -> None:
    """Print machine JSON to stdout and a redacted human diagnostic to stderr."""

    safe_message = redact_text(message)
    safe_details = redact_value(details)
    payload: dict[str, Any] = {"error": {"code": code, "message": safe_message}}
    if details is not None:
        payload["error"]["details"] = safe_details
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    diagnostic = safe_message
    if details is not None:
        diagnostic += " " + json.dumps(safe_details, ensure_ascii=False, default=str)
    log(f"{code}: {diagnostic}", "error")
    raise SystemExit(1)


def log(msg: str, level: str = "info") -> None:
    """Write a redacted human-readable diagnostic to stderr."""

    ts = time.strftime("%H:%M:%S")
    sys.stderr.write(f"[{ts}] [{level}] {redact_text(msg)}\n")
    sys.stderr.flush()


def run_subprocess(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run subprocess, returning ``(exit_code, stdout, stderr)`` safely."""

    timeout = _positive_int(timeout, "timeout")
    try:
        result = subprocess.run(
            [str(item) for item in cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except Exception as exc:
        return -1, "", redact_text(exc)


def run_seedhub(
    args: list[str],
    timeout: int | None = None,
    *,
    settings: Settings | None = None,
) -> dict | list | None:
    """Run the repository-relative seedhub CLI and parse its JSON output."""

    resolved = settings or SETTINGS
    effective_timeout = resolved.network_timeout if timeout is None else timeout
    cmd = [str(resolved.venv_python), str(resolved.seedhub_cli)] + list(args) + ["--json"]
    code, out, err = run_subprocess(cmd, timeout=effective_timeout)
    parsed: dict | list | None = None
    if out.strip():
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = None
    if code != 0:
        if isinstance(parsed, dict) and "__error__" in parsed:
            return parsed
        log(f"seedhub.py failed: {err.strip()}", "error")
        return None
    if parsed is not None:
        return parsed
    log("seedhub.py output not valid JSON", "error")
    return None


def run_bdpan(
    args: list[str],
    timeout: int | None = None,
    *,
    settings: Settings | None = None,
) -> tuple[int, str, str]:
    """Run bdpan through the resolved binary and timeout settings."""

    resolved = settings or SETTINGS
    effective_timeout = resolved.bdpan_timeout if timeout is None else timeout
    cmd = [str(resolved.bdpan_bin)] + list(args)
    return run_subprocess(cmd, timeout=effective_timeout)


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add shared CLI args."""

    parser.add_argument(
        "--quiet", "-q", action="store_true", help="静默模式（只输出 JSON）"
    )


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Read a simple dotenv file without mutating ``os.environ``."""

    env_path = Path(path) if path is not None else SKILL_ROOT / ".env"
    if not env_path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key] = value
    return env


# Loaded once at import time; tests and embedders can call load_settings(path)
# explicitly without mutating the process-wide command settings.
SETTINGS = load_settings()
VENV_PYTHON = SETTINGS.venv_python
SEEDHUB_CLI = SETTINGS.seedhub_cli
BDPAN_BIN = SETTINGS.bdpan_bin
BDPAN_BASE = SETTINGS.bdpan_base
DEFAULT_LIB = SETTINGS.bdpan_lib
NETWORK_TIMEOUT = SETTINGS.network_timeout
BDPAN_TIMEOUT = SETTINGS.bdpan_timeout


def retry(
    func: Callable[[], Any],
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Any:
    """Retry a function with exponential backoff."""

    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    current_delay = delay
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except exceptions as exc:
            last_exc = exc
            if attempt < max_attempts:
                log(f"retry {attempt}/{max_attempts} after error: {exc}", "warn")
                time.sleep(current_delay)
                current_delay *= backoff
    if last_exc is None:
        raise RuntimeError("retry did not execute")
    raise last_exc
