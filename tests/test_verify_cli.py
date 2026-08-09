from __future__ import annotations

import json
import contextlib
import importlib.machinery
import importlib.util
import io
import sys
from unittest import mock
import unittest
from pathlib import Path

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY = REPO_ROOT / "bin" / "panlib-verify"
PASSWORD = "z9x8"


def _load_verify_module():
    loader = importlib.machinery.SourceFileLoader("panlib_verify_under_test", str(VERIFY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifyCliTests(unittest.TestCase):
    def run_cli(self, url: str, *, response=None, exception=None):
        module = _load_verify_module()
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [str(VERIFY), "--url", url]
        with mock.patch.object(sys, "argv", argv):
            with mock.patch.object(
                module.httpx,
                "head",
                side_effect=exception,
                return_value=response,
            ):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        module.main()
        return raised.exception.code, stdout.getvalue(), stderr.getvalue()

    def test_timeout_and_connection_failures_are_network_and_redacted(self):
        cases = [
            (
                f"https://pan.baidu.com/s/fake-timeout?pwd={PASSWORD}",
                httpx.ReadTimeout("timed out"),
            ),
            (
                f"https://pan.baidu.com/s/fake-connection?pwd={PASSWORD}",
                httpx.ConnectError("connection refused"),
            ),
        ]
        for url, exception in cases:
            with self.subTest(url=url):
                return_code, stdout, stderr = self.run_cli(url, exception=exception)
                self.assertNotEqual(return_code, 0)
                payload = json.loads(stdout)
                self.assertEqual(payload["error"]["code"], "NETWORK")
                output = stdout + stderr
                self.assertNotIn(PASSWORD, output)
                self.assertNotIn(url, output)
                self.assertNotIn("https://", stderr)

    def test_confirmed_http_missing_or_expired_is_not_found_without_url_echo(self):
        for status in (404, 410):
            url = f"https://pan.baidu.com/s/fake-missing?pwd={PASSWORD}"
            response = httpx.Response(status, request=httpx.Request("HEAD", url))
            return_code, stdout, stderr = self.run_cli(url, response=response)
            with self.subTest(status=status):
                self.assertNotEqual(return_code, 0)
                payload = json.loads(stdout)
                self.assertEqual(payload["error"]["code"], "NOT_FOUND")
                self.assertEqual(payload["error"]["details"]["status_code"], status)
                output = stdout + stderr
                self.assertNotIn(PASSWORD, output)
                self.assertNotIn(url, output)

    def test_success_json_has_one_minimal_status_record_not_password_bearing_url(self):
        url = f"https://pan.baidu.com/s/fake-valid?pwd={PASSWORD}"
        response = httpx.Response(200, request=httpx.Request("HEAD", url))
        return_code, stdout, stderr = self.run_cli(url, response=response)
        self.assertEqual(return_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["data"], {"valid": True, "status_code": 200})
        self.assertNotIn("url", payload["data"])
        self.assertNotIn("full_url_with_pwd", stdout)
        self.assertNotIn(f"?pwd={PASSWORD}", stdout + stderr)

    def test_rejects_non_baidu_http_credentials_fragments_and_bad_queries_before_network(self):
        cases = (
            "http://pan.baidu.com/s/fake-valid",
            "https://example.invalid/s/fake-valid",
            "https://user@pan.baidu.com/s/fake-valid",
            "https://pan.baidu.com/s/fake-valid#fragment",
            "https://pan.baidu.com/s/fake-valid?next=https://127.0.0.1/",
            "https://pan.baidu.com/not-a-share",
        )
        for url in cases:
            with self.subTest(url=url):
                return_code, stdout, stderr = self.run_cli(url, response=None)
                self.assertNotEqual(return_code, 0)
                self.assertEqual(json.loads(stdout)["error"]["code"], "INVALID_ARG")
                self.assertNotIn(url, stdout + stderr)

    def test_rejects_redirect_off_official_host_without_following_it(self):
        url = "https://pan.baidu.com/s/fake-redirect"
        redirect = httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private"},
            request=httpx.Request("HEAD", url),
        )
        module = _load_verify_module()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", [str(VERIFY), "--url", url]):
            with mock.patch.object(module.httpx, "head", return_value=redirect) as head:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        module.main()
        self.assertNotEqual(raised.exception.code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], "INVALID_ARG")
        self.assertEqual(head.call_count, 1)
        self.assertNotIn("127.0.0.1", stdout.getvalue() + stderr.getvalue())

    def test_rejects_unknown_same_host_redirect_but_allows_known_share_init(self):
        url = "https://pan.baidu.com/s/fake-redirect"
        bad = httpx.Response(
            302,
            headers={"location": "https://pan.baidu.com/not-a-share"},
            request=httpx.Request("HEAD", url),
        )
        code, stdout, _ = self.run_cli(url, response=bad)
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["error"]["code"], "INVALID_ARG")

        good = httpx.Response(
            302,
            headers={"location": "/share/init?surl=fake-redirect"},
            request=httpx.Request("HEAD", url),
        )
        ok = httpx.Response(
            200,
            request=httpx.Request("HEAD", "https://pan.baidu.com/share/init?surl=fake-redirect"),
        )
        module = _load_verify_module()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", [str(VERIFY), "--url", url]):
            with mock.patch.object(module.httpx, "head", side_effect=[good, ok]) as head:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        module.main()
        self.assertEqual(raised.exception.code, 0, stderr.getvalue())
        self.assertEqual(head.call_count, 2)

    def test_rejects_unknown_or_malformed_same_host_redirect_queries(self):
        url = "https://pan.baidu.com/s/fake-redirect"
        unsafe_locations = (
            "https://pan.baidu.com/s/fake-valid?next=https://127.0.0.1/",
            "https://pan.baidu.com/share/init?next=private",
            "https://pan.baidu.com/share/init?surl=",
            "https://pan.baidu.com/share/init?surl=bad/value",
        )
        for location in unsafe_locations:
            with self.subTest(location=location):
                response = httpx.Response(
                    302,
                    headers={"location": location},
                    request=httpx.Request("HEAD", url),
                )
                code, stdout, _ = self.run_cli(url, response=response)
                self.assertNotEqual(code, 0)
                self.assertEqual(json.loads(stdout)["error"]["code"], "INVALID_ARG")

    def test_accepts_official_share_init_redirect_with_single_password(self):
        url = "https://pan.baidu.com/s/fake-redirect"
        redirect = httpx.Response(
            302,
            headers={"location": f"/share/init?surl=fake-redirect&pwd={PASSWORD}"},
            request=httpx.Request("HEAD", url),
        )
        ok = httpx.Response(
            200,
            request=httpx.Request(
                "HEAD",
                f"https://pan.baidu.com/share/init?surl=fake-redirect&pwd={PASSWORD}",
            ),
        )
        module = _load_verify_module()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", [str(VERIFY), "--url", url]):
            with mock.patch.object(module.httpx, "head", side_effect=[redirect, ok]) as head:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        module.main()
        self.assertEqual(raised.exception.code, 0, stderr.getvalue())
        self.assertEqual(head.call_count, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["data"], {"valid": True, "status_code": 200})
        self.assertNotIn(PASSWORD, stdout.getvalue() + stderr.getvalue())

    def test_redirect_without_location_is_network_not_not_found(self):
        url = "https://pan.baidu.com/s/fake-redirect"
        response = httpx.Response(302, request=httpx.Request("HEAD", url))
        code, stdout, _ = self.run_cli(url, response=response)
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["error"]["code"], "NETWORK")


if __name__ == "__main__":
    unittest.main()
