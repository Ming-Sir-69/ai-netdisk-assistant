#!/usr/bin/env python3
"""Unattended credential refresh for MCP + bdpan via Kimi WebBridge.

Both Baidu OAuth credentials this project depends on eventually need a
browser-driven re-authorization step that a headless cron job cannot do on
its own:

- MCP (mcp-pan.baidu.com) uses the Implicit Grant flow. Its access token is
  fixed at 30 days by Baidu and *cannot be refreshed* — there is no
  refresh_token in this flow. Reauth means opening the official authorize
  URL in a real, already-logged-in browser and reading the token straight
  off the resulting redirect URL.
- bdpan uses the Authorization Code flow and holds a refresh_token (Baidu
  docs: 10-year validity), so ``bdpan`` itself can silently refresh the
  access_token on any command it runs. The failure mode we hit in practice
  is neglect, not expiry: if nothing invokes bdpan for a while the stored
  access_token/refresh_token pair goes stale. Running any bdpan command
  (``whoami`` here) inside the check window is enough to keep the refresh
  cycle alive; the one-time authorization-code exchange this script performs
  is a *bootstrap or true-expiry* recovery step, not the everyday path.

This script assumes a Kimi WebBridge daemon is already running with an
extension connected in the user's real, already-authenticated browser (see
skill: kimi-webbridge). It does not touch usernames, passwords, or 2FA — it
only reads the OAuth redirect that the browser produces once the user's
existing session silently approves the request (no click required when a
prior approval exists for the same client_id/scope).

Journal: every attempt (success or failure) is appended as one JSON line to
``runtime/reauth_journal.jsonl`` in this repo, following the same
error_code/next_action shape as the rest of the project's journal so a
human or another Agent session can triage a failed run without re-deriving
the diagnosis from scratch.

Usage:
    .venv/bin/python scripts/webbridge_reauth.py --check
    .venv/bin/python scripts/webbridge_reauth.py --force-mcp
    .venv/bin/python scripts/webbridge_reauth.py --force-bdpan

Exit codes: 0 = nothing needed or refresh succeeded; 1 = a refresh was
needed and failed (see stderr + journal for the error_code).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "runtime" / "reauth_journal.jsonl"
WEBBRIDGE_URL = "http://127.0.0.1:10086/command"
WEBBRIDGE_STATUS_URL = "http://127.0.0.1:10086/status"

# MCP has no refresh_token (Implicit Grant); Baidu fixes the token at 30 days
# regardless of client. Trigger reauth once fewer than this many days remain
# so a slow/blocked WebBridge still has room to retry before a hard cutover.
MCP_REAUTH_THRESHOLD_DAYS = 5
# bdpan silently refreshes on any invocation within its 30-day window; this
# threshold only fires the interactive-code bootstrap path when the stored
# pair has actually gone stale (e.g. the host was off for a month).
BDPAN_REAUTH_THRESHOLD_DAYS = 5

# Public, non-secret OAuth client identifiers published by the upstream
# baidu-netdisk/mcp project and the bdpan CLI itself. These are the same
# constants scripts/authorize_mcp_macos.py and `bdpan login --get-auth-url`
# already use; duplicated here so this script has no import-time dependency
# on bdpan's Go binary for the MCP half.
MCP_AUTHORIZE_URL = (
    "https://openapi.baidu.com/oauth/2.0/authorize"
    "?client_id=QHOuRXiepJBMjtk0esLhrPoNlQyYd0mF"
    "&redirect_uri=oob&response_type=token&scope=basic%2Cnetdisk"
)


def _journal(event: dict) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), **event}
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _webbridge_call(action: str, args: dict, session: str = "panlib-reauth", timeout: int = 20) -> dict:
    body = json.dumps({"action": action, "args": args, "session": session}).encode("utf-8")
    req = urllib.request.Request(
        WEBBRIDGE_URL, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _webbridge_ready() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(WEBBRIDGE_STATUS_URL, timeout=5) as resp:
            status = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return False, f"WEBBRIDGE_DAEMON_UNREACHABLE: {exc}"
    if not status.get("running"):
        return False, "WEBBRIDGE_DAEMON_NOT_RUNNING"
    if not status.get("extension_connected"):
        return False, "WEBBRIDGE_EXTENSION_NOT_CONNECTED"
    return True, "ready"


def _days_until(iso_ts: str) -> float:
    expires = dt.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    return (expires - now).total_seconds() / 86400.0


def check_mcp_expiry() -> tuple[float | None, dict]:
    """Return (days_remaining, raw auth-status data). None on parse failure."""
    result = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "bin/panlib-library"), "auth-status"],
        capture_output=True, text=True, timeout=30,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, {"error": "auth-status returned non-JSON", "stdout": result.stdout[:500]}
    expires_at = payload.get("data", {}).get("expires_at")
    if not expires_at:
        return None, payload
    return _days_until(expires_at), payload


def check_bdpan_expiry() -> tuple[float | None, dict]:
    result = subprocess.run(["bdpan", "whoami", "--json"], capture_output=True, text=True, timeout=30)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, {"error": "whoami returned non-JSON", "stdout": result.stdout[:500]}
    expires_at = payload.get("expires_at")
    if not expires_at:
        return None, payload
    return _days_until(expires_at), payload


def reauth_mcp() -> bool:
    """Open the MCP implicit-grant URL, read the redirect, write the Keychain."""
    ready, reason = _webbridge_ready()
    if not ready:
        _journal({"target": "mcp", "error_code": reason, "next_action": "start_webbridge_or_reconnect_extension"})
        return False

    nav = _webbridge_call("navigate", {"url": MCP_AUTHORIZE_URL, "newTab": True, "group_title": "百度网盘MCP自动续期"})
    if not nav.get("ok"):
        _journal({"target": "mcp", "error_code": "WEBBRIDGE_NAVIGATE_FAILED", "detail": nav, "next_action": "retry_next_cycle"})
        return False

    time.sleep(2.5)
    snap = _webbridge_call("snapshot", {})
    url = snap.get("data", {}).get("url", "")
    if "login_success" not in url or "access_token=" not in url:
        _journal({
            "target": "mcp", "error_code": "MCP_REDIRECT_NOT_RECEIVED",
            "detail": {"final_url_host": url.split("?")[0].split("#")[0]},
            "next_action": "user_may_need_to_reapprove_scope_manually",
        })
        return False

    from urllib.parse import urlsplit, parse_qsl
    fragment = urlsplit(url).fragment
    params = dict(parse_qsl(fragment))
    access_token = params.get("access_token")
    expires_in = params.get("expires_in")
    scope = params.get("scope", "").replace("+", " ")
    if not access_token or not expires_in:
        _journal({"target": "mcp", "error_code": "MCP_REDIRECT_MISSING_FIELDS", "next_action": "regenerate_and_inspect_manually"})
        return False

    sys.path.insert(0, str(ROOT))
    from panlib.keychain_store import MacOSKeychain

    expires_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=int(expires_in))).isoformat()
    payload = json.dumps(
        {"access_token": access_token, "scope": scope, "expires_at_utc": expires_at},
        ensure_ascii=False, separators=(",", ":"),
    )
    keychain = MacOSKeychain.from_environment()
    keychain.set(payload)

    verify = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "bin/panlib-library"), "auth-status"],
        capture_output=True, text=True, timeout=30,
    )
    try:
        verify_payload = json.loads(verify.stdout)
        verified = verify_payload.get("data", {}).get("configured") is True
    except json.JSONDecodeError:
        verified = False

    _journal({
        "target": "mcp", "status": "verified" if verified else "written_unverified",
        "expires_at_utc": expires_at,
    })
    return verified


def reauth_bdpan() -> bool:
    """Run bdpan's own authorization-code bootstrap via the WebBridge browser."""
    ready, reason = _webbridge_ready()
    if not ready:
        _journal({"target": "bdpan", "error_code": reason, "next_action": "start_webbridge_or_reconnect_extension"})
        return False

    url_result = subprocess.run(["bdpan", "login", "--get-auth-url", "--json"], capture_output=True, text=True, timeout=15)
    try:
        auth_url = json.loads(url_result.stdout)["data"]["auth_url"]
    except (json.JSONDecodeError, KeyError):
        _journal({"target": "bdpan", "error_code": "BDPAN_GET_AUTH_URL_FAILED", "detail": url_result.stdout[:300], "next_action": "check_bdpan_install"})
        return False

    nav = _webbridge_call("navigate", {"url": auth_url, "newTab": True, "group_title": "百度网盘bdpan自动续期"})
    if not nav.get("ok"):
        _journal({"target": "bdpan", "error_code": "WEBBRIDGE_NAVIGATE_FAILED", "detail": nav, "next_action": "retry_next_cycle"})
        return False

    time.sleep(2.5)
    snap = _webbridge_call("snapshot", {})
    tree_text = json.dumps(snap.get("data", {}).get("tree", []), ensure_ascii=False)

    import re
    m = re.search(r'"value"\s*:\s*"([0-9a-f]{32})"', tree_text)
    if not m:
        _journal({"target": "bdpan", "error_code": "BDPAN_AUTH_CODE_NOT_FOUND", "next_action": "user_may_need_to_reapprove_scope_manually"})
        return False
    auth_code = m.group(1)

    login_result = subprocess.run(
        ["bdpan", "login", "--set-code", auth_code, "--json"], capture_output=True, text=True, timeout=15
    )
    try:
        login_payload = json.loads(login_result.stdout)
        ok = login_payload.get("data", {}).get("success") is True
    except json.JSONDecodeError:
        ok = False

    _journal({"target": "bdpan", "status": "verified" if ok else "login_failed", "detail": login_result.stdout[:300] if not ok else None})
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Only refresh credentials that are within their threshold")
    parser.add_argument("--force-mcp", action="store_true", help="Force MCP reauth regardless of expiry")
    parser.add_argument("--force-bdpan", action="store_true", help="Force bdpan reauth regardless of expiry")
    args = parser.parse_args()

    if not (args.check or args.force_mcp or args.force_bdpan):
        parser.print_help()
        return 1

    overall_ok = True

    if args.force_mcp or args.check:
        days, _raw = check_mcp_expiry()
        if args.force_mcp or (days is not None and days < MCP_REAUTH_THRESHOLD_DAYS):
            print(f"[mcp] reauth needed (days_remaining={days})")
            ok = reauth_mcp()
            print(f"[mcp] reauth {'succeeded' if ok else 'FAILED'}")
            overall_ok = overall_ok and ok
        else:
            print(f"[mcp] ok, {days:.1f} days remaining" if days is not None else "[mcp] status unknown, skipping")

    if args.force_bdpan or args.check:
        days, _raw = check_bdpan_expiry()
        if args.force_bdpan or (days is not None and days < BDPAN_REAUTH_THRESHOLD_DAYS):
            print(f"[bdpan] reauth needed (days_remaining={days})")
            ok = reauth_bdpan()
            print(f"[bdpan] reauth {'succeeded' if ok else 'FAILED'}")
            overall_ok = overall_ok and ok
        else:
            print(f"[bdpan] ok, {days:.1f} days remaining" if days is not None else "[bdpan] status unknown, skipping")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
