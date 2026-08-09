#!/usr/bin/env python3
"""Interactive macOS helper for storing a Baidu MCP OAuth callback.

The helper intentionally has no callback command-line option: the callback
contains the access token and is collected with :func:`getpass.getpass` only.
It opens an official Baidu authorization URL only during an explicit manual
invocation, and writes the existing Keychain JSON payload format.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import parse_qsl, urlsplit


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from panlib.keychain_store import MacOSKeychain  # noqa: E402


OFFICIAL_AUTHORIZE_HOST = "openapi.baidu.com"
# Public personal-test application link published by baidu-netdisk/mcp.  This
# is an OAuth client identifier, not a client secret.  The provider warns that
# it may change, so tests pin every non-secret parameter instead of attempting
# to invent or repair an incomplete authorization URL at runtime.
DEFAULT_AUTHORIZE_URL = (
    "https://openapi.baidu.com/oauth/2.0/authorize"
    "?client_id=QHOuRXiepJBMjtk0esLhrPoNlQyYd0mF"
    "&redirect_uri=oob&response_type=token&scope=basic%2Cnetdisk"
)


def _official_url(value: str, *, callback: bool = False) -> str:
    """Validate one official Baidu HTTPS URL without echoing its value."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("official HTTPS URL is required")
    raw = value.strip()
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise ValueError("official HTTPS URL is invalid") from exc
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("official HTTPS URL is invalid") from exc
    if (
        parts.scheme.lower() != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or port is not None
    ):
        raise ValueError("callback must use an official HTTPS URL")
    if callback:
        if host != OFFICIAL_AUTHORIZE_HOST:
            raise ValueError("callback host is not an official Baidu host")
        if parts.path != "/oauth/2.0/login_success":
            raise ValueError("callback path is not the official OAuth success path")
    else:
        if host != OFFICIAL_AUTHORIZE_HOST or not parts.path.startswith(
            "/oauth/2.0/authorize"
        ):
            raise ValueError("authorization URL is not the official Baidu endpoint")
    return raw


def _parameters(parts) -> dict[str, str]:
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    pairs += parse_qsl(parts.fragment, keep_blank_values=True)
    values: dict[str, str] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("callback contains duplicate parameters")
        values[key] = value
    return values


def parse_callback(value: str, *, now: float | None = None) -> dict[str, object]:
    """Parse a complete official OAuth callback into an in-memory payload."""

    raw = _official_url(value, callback=True)
    parts = urlsplit(raw)
    params = _parameters(parts)
    access_token = params.get("access_token", "")
    if not access_token or any(ord(char) < 32 or ord(char) == 127 for char in access_token):
        raise ValueError("callback access_token is missing or invalid")
    expires_raw = params.get("expires_in", "")
    try:
        expires_in = int(expires_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("callback expires_in is invalid") from exc
    if expires_in <= 0:
        raise ValueError("callback expires_in is invalid")
    scope = params.get("scope")
    if scope is not None and any(ord(char) < 32 or ord(char) == 127 for char in scope):
        raise ValueError("callback scope is invalid")
    return {
        "access_token": access_token,
        "scope": scope,
        "expires_in": expires_in,
        "now": now,
    }


def _payload(callback: Mapping[str, object], *, now: float | None = None) -> dict[str, object]:
    expires_in = int(callback["expires_in"])
    current = datetime.now(timezone.utc) if now is None else datetime.fromtimestamp(now, timezone.utc)
    expires_at = (current + timedelta(seconds=expires_in)).isoformat()
    payload: dict[str, object] = {
        "access_token": str(callback["access_token"]),
        "scope": callback.get("scope"),
        "expires_at_utc": expires_at,
    }
    return payload


def _authorization_url(value: str | None = None) -> str:
    raw = value or DEFAULT_AUTHORIZE_URL
    raw = _official_url(raw, callback=False)
    parts = urlsplit(raw)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    required = {
        "client_id": query.get("client_id", ""),
        "redirect_uri": "oob",
        "response_type": "token",
        "scope": "basic,netdisk",
    }
    if not required["client_id"] or any(query.get(key) != expected for key, expected in required.items()):
        raise ValueError("authorization URL does not match the official MCP personal flow")
    return raw


def authorize(
    *,
    keychain=None,
    open_browser: Callable[[str], object] | None = None,
    read_callback: Callable[[str], str] | None = None,
    force: bool = False,
    authorize_url: str | None = None,
    now: float | None = None,
) -> dict[str, object]:
    """Run one explicit interactive authorization and store its JSON payload."""

    keychain = keychain or MacOSKeychain.from_environment()
    status = keychain.status()
    if getattr(status, "reason", "") == "macos_required":
        raise RuntimeError("macOS Keychain is required")
    if getattr(status, "configured", False) and not force:
        return {"stored": False, "reason": "already_configured"}

    auth_url = _authorization_url(authorize_url)
    opener = open_browser or (lambda url: webbrowser.open(url, new=2))
    if not opener(auth_url):
        raise RuntimeError("could not open the official authorization page")
    reader = read_callback or getpass.getpass
    callback = parse_callback(reader("授权完成后粘贴官方回调 URL（输入隐藏）： "))
    stored_payload = _payload(callback, now=now if now is not None else callback.get("now"))
    keychain.set(json.dumps(stored_payload, ensure_ascii=False, separators=(",", ":")))
    return {"stored": True, "scope": stored_payload.get("scope")}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="macOS 百度 MCP 官方 OAuth 授权助手")
    parser.add_argument("--force", action="store_true", help="已有有效 Keychain 配置时也重新授权")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = authorize(force=args.force)
    except Exception:
        # Do not print exception text: an upstream Keychain/browser callback
        # implementation must never be able to echo the callback token.
        print("authorize-mcp-macos: 授权失败；未输出或保存回调内容。", file=sys.stderr)
        return 1
    if result.get("reason") == "already_configured":
        print("authorize-mcp-macos: Keychain 已有有效授权，未打开浏览器。", file=sys.stdout)
    else:
        print("authorize-mcp-macos: 授权已安全写入 macOS Keychain。", file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
