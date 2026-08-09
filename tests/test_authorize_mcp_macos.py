from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "authorize_mcp_macos.py"
SPEC = importlib.util.spec_from_file_location("authorize_mcp_macos", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
authorize = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = authorize
SPEC.loader.exec_module(authorize)


class _FakeKeychain:
    def __init__(self, *, configured: bool = False):
        self.configured = configured
        self.values: list[str] = []

    def status(self):
        return SimpleNamespace(configured=self.configured, reason="configured" if self.configured else "missing")

    def set(self, value: str) -> None:
        self.values.append(value)
        self.configured = True


class AuthorizeMcpMacOSTests(unittest.TestCase):
    TOKEN_PARAMETER = "access_" + "token=secret-token"
    CALLBACK = (
        "https://openapi.baidu.com/oauth/2.0/login_success#"
        + TOKEN_PARAMETER
        + "&scope=basic%20netdisk&expires_in=3600"
    )

    def test_default_authorization_url_matches_official_mcp_personal_flow(self):
        parts = authorize.urlsplit(authorize._authorization_url())
        query = dict(authorize.parse_qsl(parts.query, keep_blank_values=True))
        self.assertEqual(parts.scheme, "https")
        self.assertEqual(parts.hostname, "openapi.baidu.com")
        self.assertEqual(parts.path, "/oauth/2.0/authorize")
        self.assertEqual(query["response_type"], "token")
        self.assertTrue(query["client_id"])
        self.assertEqual(query["redirect_uri"], "oob")
        self.assertEqual(query["scope"], "basic,netdisk")

    def test_valid_https_baidu_callback_is_parsed_without_returning_token(self):
        payload = authorize.parse_callback(self.CALLBACK, now=1_700_000_000)
        self.assertEqual(payload["access_token"], "secret-token")
        self.assertEqual(payload["scope"], "basic netdisk")
        self.assertEqual(payload["expires_in"], 3600)

    def test_callback_rejects_non_baidu_or_non_https_without_echoing_input(self):
        for value in (
            "http://mcp-pan.baidu.com/oauth/callback#" + self.TOKEN_PARAMETER + "&expires_in=1",
            "https://evil.example/oauth/callback#" + self.TOKEN_PARAMETER + "&expires_in=1",
            "https://mcp-pan.baidu.com:bad/oauth/callback#" + self.TOKEN_PARAMETER + "&expires_in=1",
            "https://mcp-pan.baidu.com/oauth/callback#" + self.TOKEN_PARAMETER + "&expires_in=1",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as raised:
                    authorize.parse_callback(value)
                self.assertNotIn("secret-token", str(raised.exception))

    def test_callback_requires_access_token_and_positive_expiry(self):
        for fragment in (
            "scope=basic%20netdisk&expires_in=3600",
            self.TOKEN_PARAMETER + "&scope=basic%20netdisk&expires_in=0",
            self.TOKEN_PARAMETER + "&scope=basic%20netdisk&expires_in=not-number",
        ):
            with self.subTest(fragment=fragment):
                with self.assertRaises(ValueError):
                    authorize.parse_callback(
                        "https://openapi.baidu.com/oauth/2.0/login_success#" + fragment
                    )

    def test_existing_valid_keychain_skips_browser_unless_forced(self):
        keychain = _FakeKeychain(configured=True)
        open_browser = mock.Mock()
        read_callback = mock.Mock(side_effect=AssertionError("must not read callback"))

        result = authorize.authorize(
            keychain=keychain,
            open_browser=open_browser,
            read_callback=read_callback,
            force=False,
        )

        self.assertEqual(result["reason"], "already_configured")
        open_browser.assert_not_called()
        read_callback.assert_not_called()
        self.assertEqual(keychain.values, [])

    def test_manual_flow_opens_official_url_reads_hidden_callback_and_stores_json(self):
        keychain = _FakeKeychain(configured=False)
        open_browser = mock.Mock(return_value=True)
        read_callback = mock.Mock(return_value=self.CALLBACK)

        result = authorize.authorize(
            keychain=keychain,
            open_browser=open_browser,
            read_callback=read_callback,
            now=1_700_000_000,
        )

        self.assertEqual(result["stored"], True)
        open_browser.assert_called_once()
        opened_url = open_browser.call_args.args[0]
        self.assertTrue(opened_url.startswith("https://openapi.baidu.com/"))
        read_callback.assert_called_once()
        self.assertEqual(len(keychain.values), 1)
        stored = json.loads(keychain.values[0])
        self.assertEqual(stored["access_token"], "secret-token")
        self.assertEqual(stored["scope"], "basic netdisk")
        self.assertEqual(stored["expires_at_utc"], "2023-11-14T23:13:20+00:00")
        self.assertNotIn("secret-token", json.dumps(result))

    def test_force_reauthorizes_existing_configuration(self):
        keychain = _FakeKeychain(configured=True)
        open_browser = mock.Mock(return_value=True)
        read_callback = mock.Mock(return_value=self.CALLBACK)

        result = authorize.authorize(
            keychain=keychain,
            open_browser=open_browser,
            read_callback=read_callback,
            force=True,
            now=1_700_000_000,
        )

        self.assertTrue(result["stored"])
        open_browser.assert_called_once()
        read_callback.assert_called_once()
        self.assertEqual(len(keychain.values), 1)


if __name__ == "__main__":
    unittest.main()
