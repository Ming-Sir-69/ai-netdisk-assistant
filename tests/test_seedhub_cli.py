from __future__ import annotations

import json
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
SEARCH = REPO_ROOT / "bin" / "panlib-search"
EXTRACT = REPO_ROOT / "bin" / "panlib-extract"
VENDOR = REPO_ROOT / "vendor" / "seedhub-cli" / "seedhub.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "seedhub"
BASE = "https://seedhub.example"
PASSWORD = "z9x8"
SHARE_URL = "https://pan.baidu.example/s/fake-share-90001"


def _load_vendor_module():
    loader = importlib.machinery.SourceFileLoader("seedhub_vendor_under_test", str(VENDOR))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeedhubCliTests(unittest.TestCase):
    def assert_reserved_fixture_urls(self, output: str):
        allowed_hosts = {"seedhub.example", "pan.baidu.example"}
        for raw_url in re.findall(r"https?://[^\s\"<>]+", output):
            self.assertIn(urlparse(raw_url).hostname, allowed_hosts)

    def run_cli(self, script: Path, args: list[str], *, env_overrides: dict[str, str] | None = None):
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def run_vendor(self, args: list[str], *, env_overrides: dict[str, str] | None = None):
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, str(VENDOR), *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_fixtures_use_reserved_example_hosts_and_fake_codes(self):
        text = "\n".join(path.read_text(encoding="utf-8") for path in FIXTURES.glob("*.html"))
        self.assertIn(".example", text)
        self.assertNotIn("seeduck.cc", text)
        self.assertNotIn("pan.baidu.com", text)
        self.assertNotIn("BDUSS", text)
        self.assertIn(PASSWORD, text)

    def test_search_uses_real_vendor_parser_offline_and_filters_type(self):
        proc = self.run_cli(
            SEARCH,
            [
                "--keyword", "Fixture Film", "--type", "movie", "--limit", "2",
                "--fixture-dir", str(FIXTURES),
            ],
            env_overrides={"SEEDHUB_BASE": BASE},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["meta"]["count"], 1)
        self.assertEqual(payload["data"]["results"], [{
            "title": "Fixture Film",
            "info": "2020 / 电影",
            "rating": "8.8",
            "id": "90001",
            "url": f"{BASE}/movies/90001/",
        }])
        self.assertNotIn("seeduck.cc", proc.stdout)
        self.assertNotIn("seedhub.cc", proc.stdout)
        self.assert_reserved_fixture_urls(proc.stdout)

    def test_extract_uses_real_vendor_parser_and_keeps_password_separate(self):
        proc = self.run_cli(
            EXTRACT,
            ["--resource-id", "90001", "--limit", "1", "--fixture-dir", str(FIXTURES)],
            env_overrides={"SEEDHUB_BASE": BASE},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["meta"]["count"], 1)
        link = payload["data"]["links"][0]
        self.assertEqual(link["url"], SHARE_URL)
        self.assertEqual(link["password"], PASSWORD)
        self.assertEqual(link["quality"], "1080p.BluRay")
        self.assertEqual(link["resource_type"], "movie")
        self.assertNotIn("full_url_with_pwd", link)
        self.assertNotIn(f"{SHARE_URL}?pwd={PASSWORD}", proc.stdout)
        self.assertNotIn("seeduck.cc", proc.stdout)
        self.assertNotIn("seedhub.cc", proc.stdout)
        self.assert_reserved_fixture_urls(proc.stdout)
        self.assertEqual(proc.stdout.count(SHARE_URL), 1)

    def test_malformed_fixture_returns_parse_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp)
            shutil.copy2(FIXTURES / "detail.html", fixture_dir / "detail.html")
            (fixture_dir / "search.html").write_text("<html><body>broken</body></html>", encoding="utf-8")
            proc = self.run_cli(
                SEARCH,
                ["--keyword", "Fixture Film", "--fixture-dir", str(fixture_dir)],
            )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"]["code"], "PARSE")
        self.assertIn("error", payload)

    def test_malformed_detail_fixture_returns_parse_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp)
            shutil.copy2(FIXTURES / "search.html", fixture_dir / "search.html")
            (fixture_dir / "detail.html").write_text("<html><body>broken</body></html>", encoding="utf-8")
            proc = self.run_cli(
                EXTRACT,
                ["--resource-id", "90001", "--fixture-dir", str(fixture_dir)],
            )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"]["code"], "PARSE")
        self.assertNotIn(PASSWORD, proc.stdout + proc.stderr)

    def test_fixture_environment_without_flag_cannot_change_formal_base_or_parse_fixture(self):
        proc = self.run_vendor(
            ["search", "fixture-env-must-not-activate", "--limit", "2", "--json"],
            env_overrides={
                "SEEDHUB_FIXTURE_DIR": str(FIXTURES),
                "SEEDHUB_BASE": BASE,
                "HTTPS_PROXY": "http://127.0.0.1:1",
                "HTTP_PROXY": "http://127.0.0.1:1",
            },
        )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["__error__"]["code"], "NETWORK")
        self.assertNotIn("Fixture Film", proc.stdout)
        self.assertNotIn(BASE, proc.stdout)

    def test_live_search_transport_failure_is_network_not_empty_success(self):
        proc = self.run_cli(
            SEARCH,
            ["--keyword", "network-must-not-look-empty", "--limit", "2"],
            env_overrides={
                "HTTPS_PROXY": "http://127.0.0.1:1",
                "HTTP_PROXY": "http://127.0.0.1:1",
            },
        )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"]["code"], "NETWORK")
        self.assertNotIn("https://", proc.stderr)

    def test_vendor_non_200_and_off_host_intermediate_redirect_are_network_errors(self):
        module = _load_vendor_module()

        class Response:
            def __init__(self, status_code, text="", headers=None):
                self.status_code = status_code
                self.text = text
                self.headers = headers or {}

        class StatusScraper:
            def get(self, *_args, **_kwargs):
                return Response(503)

        with mock.patch.object(module, "create_scraper", return_value=StatusScraper()):
            with self.assertRaises(module.SeedhubNetworkError):
                module.search("failure")
            with self.assertRaises(module.SeedhubNetworkError):
                module.get_links("90001")

        detail = (
            '<h1><a>#</a> Fixture</h1>'
            '<a title="Fixture 1080p" data-link="baidu" '
            'href="/link_start/?redirect_to=pan_id_1&movie_title=Fixture">x</a>'
        )

        class RedirectScraper:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                if len(self.calls) == 1:
                    return Response(200, detail)
                return Response(302, headers={"location": "http://127.0.0.1/private"})

        scraper = RedirectScraper()
        with mock.patch.object(module, "create_scraper", return_value=scraper):
            with self.assertRaises(module.SeedhubNetworkError):
                module.get_links("90001")
        self.assertEqual(len(scraper.calls), 2)
        self.assertFalse(scraper.calls[1][1].get("allow_redirects", True))

        for unsafe in (
            "https://pan.baidu.com:bad/s/fake-share",
            "https://pan.baidu.com/s/fake-share?pwd=abcd",
            "https://pan.baidu.com/s/short",
            "https://pan.baidu.com/s/" + "a" * 65,
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(module.SeedhubNetworkError):
                    module._validated_redirect(unsafe, "baidu")

        self.assertIsNotNone(re.search(module._BAIDU_SHARE_URL_RE, SHARE_URL))
        self.assertIsNone(re.search(module._BAIDU_SHARE_URL_RE, "https://pan.baidu.com/s/short"))
        self.assertIsNone(
            re.search(
                module._BAIDU_SHARE_URL_RE,
                "https://pan.baidu.com/s/fake-share-unsafe/extra",
            )
        )
        for suffix in (".extra", "!extra", "?pwd=z9x8"):
            with self.subTest(suffix=suffix):
                self.assertIsNone(
                    re.search(
                        module._BAIDU_SHARE_URL_RE,
                        f"https://pan.baidu.com/s/fake-share-unsafe{suffix}",
                    )
                )

    def test_missing_explicit_fixture_directory_returns_parse_without_network(self):
        missing = REPO_ROOT / "tests" / "fixtures" / "seedhub" / "does-not-exist"
        proc = self.run_cli(
            SEARCH,
            ["--keyword", "Fixture Film", "--fixture-dir", str(missing)],
        )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"]["code"], "PARSE")
        self.assertNotIn("https://", proc.stderr)

    def test_vendor_nonzero_exit_returns_network_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_python = Path(tmp) / "missing-python"
            proc = self.run_cli(
                SEARCH,
                ["--keyword", "Fixture Film"],
                env_overrides={"VENV_PYTHON": str(missing_python)},
            )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"]["code"], "NETWORK")


if __name__ == "__main__":
    unittest.main()
