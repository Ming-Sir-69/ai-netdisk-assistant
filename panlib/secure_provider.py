"""Replaceable credential providers with no plaintext-file fallback.

The default provider remains the native macOS Keychain implementation.  An
explicit external-command provider is available for hosts that already have
a secure credential broker (for example a system service or test helper). The
broker is invoked with one absolute executable path, no shell, bounded JSON
stdin/stdout and a timeout; credential values never enter argv or diagnostics.
"""

from __future__ import annotations

import json
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, Mapping

try:  # scripts import panlib modules as top-level
    from .keychain_store import (
        CredentialError,
        CredentialExpired,
        CredentialPayload,
        CredentialStatus,
        CredentialUnavailable,
        MacOSKeychain,
        parse_credential,
    )
except ImportError:  # pragma: no cover - exercised by bin/ bridge imports
    from keychain_store import (
        CredentialError,
        CredentialExpired,
        CredentialPayload,
        CredentialStatus,
        CredentialUnavailable,
        MacOSKeychain,
        parse_credential,
    )


Runner = Callable[..., subprocess.CompletedProcess[str]]
DEFAULT_TIMEOUT = 5.0
DEFAULT_MAX_INPUT_BYTES = 64 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024


class CredentialProvider(ABC):
    """Minimal source-independent credential contract."""

    @abstractmethod
    def status(self) -> CredentialStatus:
        raise NotImplementedError

    @abstractmethod
    def token(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def set(self, value: str) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class MacOSKeychainProvider(CredentialProvider):
    """Adapter preserving the existing native Keychain behavior exactly."""

    backend: ClassVar[str] = "macos-keychain"
    keychain: MacOSKeychain

    @classmethod
    def from_environment(cls) -> "MacOSKeychainProvider":
        return cls(MacOSKeychain.from_environment())

    def status(self) -> CredentialStatus:
        return self.keychain.status()

    def token(self) -> str:
        return self.keychain.token()

    def set(self, value: str) -> None:
        self.keychain.set(value)


@dataclass(slots=True)
class UnavailableCredentialProvider(CredentialProvider):
    """Explicit unavailable state instead of silently falling back to files."""

    backend: str
    reason: str

    def status(self) -> CredentialStatus:
        return CredentialStatus(self.backend, False, False, self.reason)

    def token(self) -> str:
        raise CredentialUnavailable(f"credential provider unavailable: {self.reason}")

    def set(self, value: str) -> None:
        raise CredentialUnavailable(f"credential provider unavailable: {self.reason}")


@dataclass(slots=True)
class ExternalCommandCredentialProvider(CredentialProvider):
    """Use one pre-installed secure helper through a bounded JSON protocol.

    Request shapes are ``{"op":"get"}`` and
    ``{"op":"set","credential":"<JSON payload>"}``. Successful helper
    responses must be ``{"ok":true,"credential":...}`` (``value`` is also
    accepted for a string payload). ``{"ok":false,"code":"MISSING"}``
    reports an unconfigured provider. All other failures are unavailable and
    intentionally do not include helper stderr.
    """

    backend: ClassVar[str] = "external-command"
    executable: str
    timeout: float = DEFAULT_TIMEOUT
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    runner: Runner = subprocess.run

    def __post_init__(self) -> None:
        path = Path(self.executable)
        if not path.is_absolute():
            raise ValueError("external credential executable must be absolute")
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("external credential executable must be executable")
        if self.timeout <= 0:
            raise ValueError("external credential timeout must be positive")
        if self.max_input_bytes <= 0 or self.max_output_bytes <= 0:
            raise ValueError("external credential size limits must be positive")

    @staticmethod
    def _text(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value if isinstance(value, str) else ""

    def _run(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise CredentialError("external credential request is invalid") from exc
        if len(encoded.encode("utf-8")) > self.max_input_bytes:
            raise CredentialUnavailable("external credential request exceeds size limit")
        try:
            result = self.runner(
                [self.executable],
                input=encoded,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CredentialUnavailable("external credential helper timed out") from exc
        except OSError as exc:
            raise CredentialUnavailable("external credential helper is unavailable") from exc
        stdout = self._text(getattr(result, "stdout", ""))
        stderr = self._text(getattr(result, "stderr", ""))
        if (
            len(stdout.encode("utf-8")) > self.max_output_bytes
            or len(stderr.encode("utf-8")) > self.max_output_bytes
        ):
            raise CredentialUnavailable("external credential response exceeds size limit")
        if getattr(result, "returncode", 1) != 0:
            raise CredentialUnavailable("external credential helper failed")
        try:
            response = json.loads(stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CredentialUnavailable("external credential response is invalid") from exc
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            raise CredentialUnavailable("external credential response is invalid")
        if not response["ok"]:
            if response.get("code") == "MISSING":
                return None
            raise CredentialUnavailable("external credential helper reported unavailable")
        return response

    def _raw(self) -> str | None:
        response = self._run({"op": "get"})
        if response is None:
            return None
        value = response.get("credential", response.get("value"))
        if isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if not isinstance(value, str) or not value.strip():
            raise CredentialUnavailable("external credential response has no credential")
        if len(value.encode("utf-8")) > self.max_output_bytes:
            raise CredentialUnavailable("external credential value exceeds size limit")
        return value.strip()

    def status(self) -> CredentialStatus:
        try:
            raw = self._raw()
        except CredentialUnavailable as exc:
            lowered = str(exc).lower()
            reason = "timeout" if "timed out" in lowered else "unavailable"
            if "size limit" in lowered:
                reason = "size_limit"
            return CredentialStatus("external-command", False, False, reason)
        except CredentialError:
            return CredentialStatus("external-command", True, False, "invalid")
        if raw is None:
            return CredentialStatus("external-command", True, False, "missing")
        try:
            payload = parse_credential(raw)
        except CredentialExpired as exc:
            return CredentialStatus(
                "external-command", True, False, "expired", expires_at=exc.expires_at
            )
        except CredentialError:
            return CredentialStatus("external-command", True, False, "invalid")
        return CredentialStatus(
            "external-command",
            True,
            True,
            "configured",
            expires_at=payload.expires_at,
            scope=payload.scope,
        )

    def token(self) -> str:
        raw = self._raw()
        if raw is None:
            raise CredentialUnavailable("external credential is missing")
        return parse_credential(raw).access_token

    def set(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("credential must not be empty")
        # Validate before passing the value to the helper, while retaining the
        # exact JSON payload format used by the existing Keychain backend.
        parse_credential(value)
        response = self._run({"op": "set", "credential": value.strip()})
        if response is None:
            raise CredentialUnavailable("external credential helper rejected write")


def secure_provider_from_environment(
    environ: Mapping[str, str] | None = None,
) -> CredentialProvider:
    """Select a provider without ever interpreting a plaintext file path."""

    env = os.environ if environ is None else environ
    backend = str(env.get("PANLIB_CREDENTIAL_BACKEND", "")).strip().lower()
    if backend in {"", "macos-keychain", "macos_keychain"}:
        return MacOSKeychainProvider.from_environment()
    if backend not in {"external-command", "external_command"}:
        return UnavailableCredentialProvider("unsupported", "unsupported_backend")
    executable = str(
        env.get("PANLIB_CREDENTIAL_COMMAND")
        or env.get("PANLIB_CREDENTIAL_HELPER")
        or ""
    ).strip()
    if not executable:
        return UnavailableCredentialProvider("external-command", "missing_command")
    try:
        timeout = float(env.get("PANLIB_CREDENTIAL_TIMEOUT", str(DEFAULT_TIMEOUT)))
        max_input = int(env.get("PANLIB_CREDENTIAL_MAX_INPUT_BYTES", str(DEFAULT_MAX_INPUT_BYTES)))
        max_output = int(env.get("PANLIB_CREDENTIAL_MAX_OUTPUT_BYTES", str(DEFAULT_MAX_OUTPUT_BYTES)))
        return ExternalCommandCredentialProvider(
            executable,
            timeout=timeout,
            max_input_bytes=max_input,
            max_output_bytes=max_output,
        )
    except (TypeError, ValueError):
        return UnavailableCredentialProvider("external-command", "invalid_configuration")


get_secure_provider = secure_provider_from_environment
