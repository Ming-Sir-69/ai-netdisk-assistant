from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from panlib.keychain_store import (
    CredentialExpired,
    MacOSKeychain,
    CredentialUnavailable,
    parse_credential,
)


class MacOSKeychainTests(unittest.TestCase):
    def test_explicit_security_compatible_executable_is_allowed_on_non_macos(self):
        with tempfile.TemporaryDirectory() as tmp:
            security = Path(tmp) / "security-compatible"
            security.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            security.chmod(0o700)

            def runner(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, "secret-access-token\n", "")

            keychain = MacOSKeychain(security=security, runner=runner)
            with mock.patch("panlib.keychain_store.sys.platform", "linux"):
                self.assertEqual(keychain.get(), "secret-access-token")

    def test_store_passes_secret_as_argv_not_stdin(self):
        """凭据必须作为 argv 尾参传入，不得走交互式 stdin。

        2026-08-30 实测：``security add-generic-password -w`` 从 stdin 读值时，
        在 128 字节处静默截断——178 字节的 JSON 写入后读回恰好 128 字节，
        无报错、退出码为 0。MCP OAuth payload 与 bdpan token 对均超过 128 字节，
        该路径此前一直在静默损坏凭据。

        本测试原先断言相反行为（secret 不得出现在 argv、必须走 stdin），
        锁死的正是这个已被证伪的假设。取舍：值在短命子进程存活期间对同用户的
        ps 可见；单用户 agent 主机上，这优于静默数据损坏。铭哥已确认接受。

        任何把 set() 改回 stdin 传参的改动都会让这个测试失败——这是预期的回归防线。
        """
        calls: list[tuple[list[str], str | None]] = []

        def runner(argv, **kwargs):
            calls.append((list(argv), kwargs.get("input")))
            return subprocess.CompletedProcess(argv, 0, "", "")

        keychain = MacOSKeychain(
            service="com.example.test",
            account="mcp",
            security="/usr/bin/security",
            runner=runner,
        )
        with mock.patch("panlib.keychain_store.sys.platform", "darwin"):
            keychain.set("secret-access-token")

        self.assertEqual(len(calls), 1)
        argv, supplied = calls[0]
        self.assertEqual(argv[:2], ["/usr/bin/security", "add-generic-password"])
        self.assertIn("-w", argv)
        # 值必须紧跟 -w 作为 argv 尾参
        self.assertEqual(argv[argv.index("-w") + 1], "secret-access-token")
        # 且不得再走 stdin（交互式路径正是截断的来源）
        self.assertIsNone(supplied)

    def test_store_survives_payload_over_128_bytes(self):
        """超过 128 字节的凭据必须完整传递——这是截断事故的直接回归防线。"""
        payload = "x" * 200
        calls: list[list[str]] = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")

        keychain = MacOSKeychain(
            service="com.example.test",
            account="mcp",
            security="/usr/bin/security",
            runner=runner,
        )
        with mock.patch("panlib.keychain_store.sys.platform", "darwin"):
            keychain.set(payload)

        argv = calls[0]
        self.assertEqual(argv[argv.index("-w") + 1], payload)
        self.assertEqual(len(argv[argv.index("-w") + 1]), 200)

    def test_get_reads_keychain_without_plaintext_fallback(self):
        calls: list[list[str]] = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "secret-access-token\n", "")

        keychain = MacOSKeychain(
            service="com.example.test",
            account="mcp",
            security="/usr/bin/security",
            runner=runner,
        )
        with mock.patch("panlib.keychain_store.sys.platform", "darwin"):
            self.assertEqual(keychain.get(), "secret-access-token")
        self.assertNotIn("secret-access-token", calls[0])

    def test_status_distinguishes_missing_item_and_unavailable_platform(self):
        def missing_runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 44, "", "The specified item could not be found")

        keychain = MacOSKeychain(runner=missing_runner)
        with mock.patch("panlib.keychain_store.sys.platform", "darwin"):
            status = keychain.status()
        self.assertFalse(status.configured)
        self.assertTrue(status.available)
        self.assertEqual(status.reason, "missing")

        with mock.patch("panlib.keychain_store.sys.platform", "linux"):
            unavailable = keychain.status()
        self.assertFalse(unavailable.available)
        self.assertEqual(unavailable.reason, "macos_required")
        with mock.patch("panlib.keychain_store.sys.platform", "linux"):
            with self.assertRaises(CredentialUnavailable):
                keychain.get()

    def test_json_oauth_payload_is_parsed_and_expiry_is_enforced(self):
        payload = parse_credential(
            '{"access_token":"secret-access-token","scope":"netdisk","expires_at":200}',
            now=100,
        )
        self.assertEqual(payload.access_token, "secret-access-token")
        self.assertEqual(payload.scope, "netdisk")
        self.assertEqual(payload.expires_at, "200")
        with self.assertRaises(CredentialExpired) as raised:
            parse_credential(
                '{"access_token":"secret-access-token","scope":"netdisk","expires_at":100}',
                now=100,
            )
        self.assertEqual(raised.exception.expires_at, "100")

    def test_legacy_bare_token_remains_compatible_without_expiry(self):
        payload = parse_credential("legacy-token", now=9999999999)
        self.assertEqual(payload.access_token, "legacy-token")
        self.assertIsNone(payload.expires_at)

    def test_existing_keychain_payload_uses_expires_at_utc(self):
        payload = parse_credential(
            '{"access_token":"secret-access-token","scope":"file_list file_move",'
            '"expires_at_utc":"2099-01-01T00:00:00Z"}',
            now=100,
        )
        self.assertEqual(payload.expires_at, "2099-01-01T00:00:00Z")
        with self.assertRaises(CredentialExpired):
            parse_credential(
                '{"access_token":"secret-access-token","expires_at_utc":"2000-01-01T00:00:00Z"}',
                now=2_000_000_000,
            )


if __name__ == "__main__":
    unittest.main()
