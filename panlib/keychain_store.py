"""macOS Keychain storage for the official Baidu MCP credential.

The first supported credential backend is deliberately macOS-only.  The
``security`` command is used without a plaintext-file fallback; callers may
inject a runner for tests, while production values remain in the login
Keychain.  A token is supplied to ``security`` over stdin and is never placed
in argv, logs, JSON output or project files.
"""

from __future__ import annotations

import os
import getpass
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class CredentialUnavailable(RuntimeError):
    """The macOS Keychain backend cannot be used in this environment."""


class CredentialError(RuntimeError):
    """A Keychain operation failed after the backend was available."""


class CredentialExpired(CredentialError):
    """The stored OAuth payload has passed its explicit expiry time."""

    def __init__(self, message: str, expires_at: str | None = None):
        super().__init__(message)
        self.expires_at = expires_at


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    backend: str
    available: bool
    configured: bool
    reason: str
    expires_at: str | None = None
    scope: str | None = None


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(slots=True)
class MacOSKeychain:
    """Small native wrapper around ``/usr/bin/security`` generic passwords."""

    service: str = "ai-netdisk-manager.baidu-mcp.oauth"
    account: str = getpass.getuser()
    security: str | Path = "/usr/bin/security"
    runner: Runner = subprocess.run

    @classmethod
    def from_environment(cls) -> "MacOSKeychain":
        return cls(
            service=os.environ.get(
                "PANLIB_KEYCHAIN_SERVICE", "ai-netdisk-manager.baidu-mcp.oauth"
            ),
            account=os.environ.get("PANLIB_KEYCHAIN_ACCOUNT", getpass.getuser()),
            security=os.environ.get("PANLIB_KEYCHAIN_SECURITY", "/usr/bin/security"),
        )

    @property
    def backend(self) -> str:
        return "macos-keychain"

    def _ensure_available(self) -> None:
        if sys.platform != "darwin":
            raise CredentialUnavailable("macOS Keychain is required")
        executable = str(self.security)
        if not (Path(executable).is_file() or shutil.which(executable)):
            raise CredentialUnavailable("macOS security command is unavailable")

    def _invoke(
        self,
        arguments: Sequence[str],
        *,
        secret_input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self._ensure_available()
        argv = [str(self.security), *arguments]
        # ``-w`` is intentionally the final option.  security then prompts
        # for the value; input is supplied through the child pipe, never argv.
        try:
            timeout = float(os.environ.get("PANLIB_KEYCHAIN_TIMEOUT", "5"))
        except ValueError as exc:
            raise CredentialUnavailable("Keychain timeout is invalid") from exc
        if timeout <= 0:
            raise CredentialUnavailable("Keychain timeout must be positive")
        try:
            return self.runner(
                argv,
                input=None if secret_input is None else secret_input + "\n",
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CredentialUnavailable("macOS Keychain operation timed out") from exc

    def get(self) -> str | None:
        result = self._invoke(
            [
                "find-generic-password",
                "-a",
                self.account,
                "-s",
                self.service,
                "-w",
            ]
        )
        if result.returncode != 0:
            if result.returncode in {44, 45}:
                return None
            raise CredentialError("macOS Keychain read failed")
        value = (result.stdout or "").strip()
        return value or None

    def set(self, token: str) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("credential must not be empty")
        secret = token.strip()
        result = self._invoke(
            [
                "add-generic-password",
                "-U",
                "-a",
                self.account,
                "-s",
                self.service,
                "-w",
            ],
            # ``security add-generic-password -w`` prompts for the new value
            # twice.  Feed both hidden prompts over stdin while keeping the
            # value out of argv, logs and project files.
            secret_input=f"{secret}\n{secret}",
        )
        if result.returncode != 0:
            raise CredentialError("macOS Keychain write failed")

    def clear(self) -> None:
        result = self._invoke(
            [
                "delete-generic-password",
                "-a",
                self.account,
                "-s",
                self.service,
            ]
        )
        if result.returncode not in {0, 44, 45}:
            raise CredentialError("macOS Keychain delete failed")

    def status(self) -> CredentialStatus:
        if sys.platform != "darwin":
            return CredentialStatus(self.backend, False, False, "macos_required")
        try:
            raw = self.get()
        except CredentialUnavailable:
            return CredentialStatus(self.backend, False, False, "security_unavailable")
        except CredentialError:
            return CredentialStatus(self.backend, True, False, "error")
        if not raw:
            return CredentialStatus(self.backend, True, False, "missing")
        try:
            payload = parse_credential(raw)
        except CredentialExpired as exc:
            return CredentialStatus(
                self.backend,
                True,
                False,
                "expired",
                expires_at=exc.expires_at,
            )
        except CredentialError:
            return CredentialStatus(self.backend, True, False, "invalid")
        return CredentialStatus(
            self.backend,
            True,
            True,
            "configured",
            expires_at=payload.expires_at,
            scope=payload.scope,
        )

    def token(self) -> str:
        """Return a live token in memory for the bundled bridge only."""

        raw = self.get()
        if not raw:
            raise CredentialError("macOS Keychain credential is missing")
        return parse_credential(raw).access_token


@dataclass(frozen=True, slots=True)
class CredentialPayload:
    access_token: str
    scope: str | None
    expires_at: str | None
    expires_epoch: float | None


def _parse_expiry(value: object) -> tuple[str | None, float | None]:
    if value is None or value == "":
        return None, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
        # OAuth stores seconds in this project; accept millisecond payloads
        # from older clients without exposing the raw value.
        if epoch > 100_000_000_000:
            epoch /= 1000
        return str(value), epoch
    if isinstance(value, str):
        raw = value.strip()
        try:
            epoch = float(raw)
        except ValueError:
            try:
                iso = raw.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(iso)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return raw, parsed.timestamp()
            except ValueError as exc:
                raise CredentialError("credential expiry is invalid") from exc
        if epoch > 100_000_000_000:
            epoch /= 1000
        return raw, epoch
    raise CredentialError("credential expiry is invalid")


def parse_credential(raw: str, *, now: float | None = None) -> CredentialPayload:
    """Parse the current JSON Keychain payload and legacy bare-token values."""

    if not isinstance(raw, str) or not raw.strip():
        raise CredentialError("credential is empty")
    text = raw.strip()
    payload: object = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = text  # legacy bare token
    if isinstance(payload, str):
        token = payload.strip()
        scope = None
        expiry_value = None
    elif isinstance(payload, dict):
        token = payload.get("access_token") or payload.get("token")
        scope_value = payload.get("scope")
        scope = str(scope_value) if scope_value is not None else None
        expiry_value = payload.get("expires_at")
        if expiry_value in (None, ""):
            expiry_value = payload.get("expires_at_utc")
    else:
        raise CredentialError("credential payload is invalid")
    if not isinstance(token, str) or not token.strip():
        raise CredentialError("credential payload has no access_token")
    expires_at, expires_epoch = _parse_expiry(expiry_value)
    if expires_epoch is not None:
        current = datetime.now(timezone.utc).timestamp() if now is None else now
        if expires_epoch <= current:
            raise CredentialExpired("macOS Keychain credential has expired", expires_at)
    return CredentialPayload(token.strip(), scope, expires_at, expires_epoch)
