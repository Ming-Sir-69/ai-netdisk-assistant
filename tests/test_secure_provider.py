from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from panlib.secure_provider import (
    ExternalCommandCredentialProvider,
    MacOSKeychainProvider,
    secure_provider_from_environment,
)
from panlib.keychain_store import CredentialUnavailable


class CredentialProviderTests(unittest.TestCase):
    HELPER = "/bin/echo"
    LIBRARY = Path(__file__).resolve().parents[1] / "bin" / "panlib-library"
    BRIDGE = Path(__file__).resolve().parents[1] / "bin" / "panlib-mcp-bridge"

    def test_external_command_requires_absolute_executable_without_shell(self):
        with self.assertRaises(ValueError):
            ExternalCommandCredentialProvider("relative-helper")
        with self.assertRaises(ValueError):
            ExternalCommandCredentialProvider("/no/such/credential-helper", runner=lambda *args, **kwargs: None)

    def test_external_get_uses_structured_stdin_and_keeps_token_in_memory(self):
        calls: list[tuple[list[str], dict]] = []
        payload = {
            "ok": True,
            "credential": {
                "access_token": "secret-token",
                "scope": "file_list",
                "expires_at_utc": "2099-01-01T00:00:00Z",
            },
        }

        def runner(argv, **kwargs):
            calls.append((list(argv), kwargs))
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "helper-secret-token should stay ignored")

        provider = ExternalCommandCredentialProvider(
            self.HELPER,
            runner=runner,
        )
        token = provider.token()
        self.assertEqual(token, "secret-token")
        self.assertEqual(calls[0][0], [self.HELPER])
        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(json.loads(calls[0][1]["input"]), {"op": "get"})
        self.assertNotIn("secret-token", " ".join(calls[0][0]))

    def test_external_set_sends_json_payload_and_no_plaintext_file_fallback(self):
        calls: list[tuple[list[str], dict]] = []

        def runner(argv, **kwargs):
            calls.append((list(argv), kwargs))
            return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")

        provider = ExternalCommandCredentialProvider(self.HELPER, runner=runner)
        value = '{"access_token":"secret-token","scope":"netdisk","expires_at_utc":"2099-01-01T00:00:00Z"}'
        provider.set(value)
        request = json.loads(calls[0][1]["input"])
        self.assertEqual(request["op"], "set")
        self.assertEqual(json.loads(request["credential"])["access_token"], "secret-token")
        self.assertNotIn("secret-token", " ".join(calls[0][0]))
        self.assertFalse((Path.cwd() / "credentials.json").exists())

    def test_external_timeout_and_oversized_response_are_unavailable_without_echo(self):
        def timeout_runner(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 1)

        timeout_provider = ExternalCommandCredentialProvider(
            self.HELPER, runner=timeout_runner
        )
        with self.assertRaises(CredentialUnavailable) as timeout_error:
            timeout_provider.token()
        self.assertNotIn("secret-token", str(timeout_error.exception))

        def oversized_runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, "x" * 129, "helper-token-should-not-echo")

        oversized_provider = ExternalCommandCredentialProvider(
            self.HELPER,
            runner=oversized_runner,
            max_output_bytes=128,
        )
        with self.assertRaises(CredentialUnavailable) as oversized_error:
            oversized_provider.token()
        self.assertNotIn("helper-token-should-not-echo", str(oversized_error.exception))

    def test_factory_defaults_to_macos_provider_and_non_macos_is_clear_unavailable(self):
        with mock.patch.dict(
            os.environ,
            {"PANLIB_CREDENTIAL_BACKEND": "", "PANLIB_CREDENTIAL_COMMAND": ""},
            clear=False,
        ), mock.patch("panlib.keychain_store.sys.platform", "linux"):
            provider = secure_provider_from_environment()
            status = provider.status()
        self.assertIsInstance(provider, MacOSKeychainProvider)
        self.assertFalse(status.available)
        self.assertEqual(status.reason, "macos_required")

    def test_factory_external_backend_requires_controlled_absolute_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "helper"
            helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            helper.chmod(0o700)
            with mock.patch.dict(
                os.environ,
                {
                    "PANLIB_CREDENTIAL_BACKEND": "external-command",
                    "PANLIB_CREDENTIAL_COMMAND": str(helper),
                },
                clear=False,
            ):
                provider = secure_provider_from_environment()
            self.assertIsInstance(provider, ExternalCommandCredentialProvider)
            self.assertEqual(provider.executable, str(helper))

    def test_bundled_bridge_uses_external_provider_for_read_only_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "credential-helper.py"
            helper.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "request = json.load(sys.stdin)\n"
                "if request.get('op') == 'get':\n"
                "    print(json.dumps({'ok': True, 'credential': {'access_token': 'secret-token', 'scope': 'netdisk', 'expires_at_utc': '2099-01-01T00:00:00Z'}}))\n"
                "else:\n"
                "    print(json.dumps({'ok': True}))\n",
                encoding="utf-8",
            )
            helper.chmod(0o700)
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_CREDENTIAL_BACKEND": "external-command",
                    "PANLIB_CREDENTIAL_COMMAND": str(helper),
                }
            )
            result = subprocess.run(
                [sys.executable, str(self.BRIDGE)],
                input=json.dumps({"tool": "auth_status", "arguments": {}}),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"backend": "external-command"', result.stdout)
        self.assertNotIn("secret-token", result.stdout + result.stderr)

    def test_library_auth_store_reports_the_selected_external_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            request_file = Path(tmp) / "request.json"
            helper = Path(tmp) / "credential-helper.py"
            helper.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "request = json.load(sys.stdin)\n"
                "open(os.environ['REQUEST_FILE'], 'w', encoding='utf-8').write(json.dumps(request))\n"
                "print(json.dumps({'ok': True}))\n",
                encoding="utf-8",
            )
            helper.chmod(0o700)
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_CREDENTIAL_BACKEND": "external-command",
                    "PANLIB_CREDENTIAL_COMMAND": str(helper),
                    "REQUEST_FILE": str(request_file),
                }
            )
            credential = json.dumps(
                {
                    "access_token": "secret-token",
                    "scope": "netdisk",
                    "expires_at_utc": "2099-01-01T00:00:00Z",
                }
            )
            result = subprocess.run(
                [sys.executable, str(self.LIBRARY), "auth-store"],
                input=credential,
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            request = json.loads(request_file.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["data"]["backend"], "external-command")
        self.assertEqual(payload["meta"]["mode"], "write-secure-provider-only")
        self.assertNotIn("secret-token", result.stdout + result.stderr)
        self.assertEqual(request["op"], "set")


if __name__ == "__main__":
    unittest.main()
