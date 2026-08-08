from __future__ import annotations

import json
import importlib.machinery
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSFER = REPO_ROOT / "bin" / "panlib-transfer"
FAKE = REPO_ROOT / "tests" / "fakes" / "bdpan"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "seedhub"
FIXTURE_SHARE_URL = "https://pan.baidu.example/s/fake-share-90001"
FIXTURE_PASSWORD = "z9x8"


def _load_transfer_module():
    loader = importlib.machinery.SourceFileLoader("panlib_transfer_under_test", str(TRANSFER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TransferCliTests(unittest.TestCase):
    def run_cli(
        self,
        extra: list[str],
        *,
        state: dict | None = None,
        fake_fail: str = "",
        inject_after_ls: int | None = None,
        inject_dir: str = "",
        inject_name: str = "",
        transfer_name: str = "",
        return_state: bool = False,
    ):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        log = root / "calls.json"
        state_path = root / "state.json"
        state_path.write_text(json.dumps(state or {"directories": [], "entries": {}}), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "BDPAN_BIN": str(FAKE),
                "BDPAN_BASE": "/safe/base",
                "BDPAN_LIB": "Library",
                "BDPAN_FAKE_LOG": str(log),
                "BDPAN_FAKE_STATE": str(state_path),
            }
        )
        if fake_fail:
            env["BDPAN_FAKE_FAIL"] = fake_fail
        if inject_after_ls is not None:
            env["BDPAN_FAKE_INJECT_AFTER_LS"] = str(inject_after_ls)
            env["BDPAN_FAKE_INJECT_DIR"] = inject_dir
            env["BDPAN_FAKE_INJECT_NAME"] = inject_name
            env["BDPAN_FAKE_TRANSFER_NAME"] = inject_name
        if transfer_name:
            env["BDPAN_FAKE_TRANSFER_NAME"] = transfer_name
        proc = subprocess.run(
            [sys.executable, str(TRANSFER)] + extra,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        calls = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
        final_state = json.loads(state_path.read_text(encoding="utf-8"))
        tmp.cleanup()
        if return_state:
            return proc, calls, final_state
        return proc, calls

    def base_args(self) -> list[str]:
        return [
            "--url",
            "https://pan.baidu.com/s/1abcde",
            "--password",
            "qwer",
            "--type",
            "movie",
            "--title-en",
            "Limitless",
            "--imdb-id",
            "tt1219289",
        ]

    def resource_args(
        self,
        *,
        fixture_dir: Path = FIXTURES,
        link_index: int | None = None,
        share_ref: str | None = None,
    ) -> list[str]:
        args = [
            "--resource-id",
            "90001",
            "--type",
            "movie",
            "--title-en",
            "Limitless",
            "--imdb-id",
            "tt1219289",
            "--fixture-dir",
            str(fixture_dir),
        ]
        if link_index is not None:
            args.extend(["--link-index", str(link_index)])
        if share_ref is not None:
            args.extend(["--share-ref", share_ref])
        return args

    def _write_two_candidate_fixture(self, root: Path) -> Path:
        fixture_dir = root / "seedhub"
        fixture_dir.mkdir()
        shutil.copy2(FIXTURES / "search.html", fixture_dir / "search.html")
        detail = (FIXTURES / "detail.html").read_text(encoding="utf-8")
        detail = detail.replace(
            '</section>',
            '      <a data-link="baidu" title="Fixture Film 720p 提取码: abcd" '
            'href="/link_start/?redirect_to=pan_id_90002&movie_title=Fixture%20Film%202">'
            '百度网盘 2</a>\n'
            '    </section>',
        )
        (fixture_dir / "detail.html").write_text(detail, encoding="utf-8")
        return fixture_dir

    def _read_share_ref(self, proc: subprocess.CompletedProcess[str]) -> str:
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        share_ref = payload["data"].get("share_ref")
        self.assertIsInstance(share_ref, str)
        self.assertRegex(share_ref, r"^[0-9a-f]{64}$")
        return share_ref

    def test_resource_id_plan_resolves_inside_transfer_without_echoing_secret(self):
        proc, calls = self.run_cli(self.resource_args())
        share_ref = self._read_share_ref(proc)
        output = proc.stdout + proc.stderr
        self.assertNotIn(FIXTURE_SHARE_URL, output)
        self.assertNotIn(FIXTURE_PASSWORD, output)
        self.assertEqual(calls, [])
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["data"]["resource_id"], "90001")
        self.assertEqual(payload["data"]["link_index"], 0)
        action = payload["data"]["plan"][0]
        self.assertEqual(action["source"], "seedhub-resource")
        self.assertNotIn("url", action)
        self.assertNotIn("password", action)
        self.assertEqual(action["share_ref"], share_ref)

    def test_share_ref_does_not_encode_low_entropy_extraction_code(self):
        module = _load_transfer_module()
        first = module._share_ref("90001", 0, FIXTURE_SHARE_URL, "a1b2")
        second = module._share_ref("90001", 0, FIXTURE_SHARE_URL, "z9x8")
        self.assertEqual(first, second)
        embedded_first = module._share_ref(
            "90001", 0, f"{FIXTURE_SHARE_URL}?pwd=a1b2", ""
        )
        embedded_second = module._share_ref(
            "90001", 0, f"{FIXTURE_SHARE_URL}?pwd=z9x8", ""
        )
        self.assertEqual(embedded_first, embedded_second)

    def test_resource_id_execute_requires_plan_share_ref(self):
        proc, calls = self.run_cli(self.resource_args() + ["--execute"])
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"]["code"], "INVALID_ARG")
        self.assertIn("share_ref", payload["error"]["message"])
        self.assertEqual(calls, [])
        self.assertNotIn(FIXTURE_SHARE_URL, proc.stdout + proc.stderr)
        self.assertNotIn(FIXTURE_PASSWORD, proc.stdout + proc.stderr)

    def test_resource_id_execute_reuses_selected_link_and_keeps_secret_internal(self):
        state = {
            "directories": ["/safe/base/Library/Movies"],
            "entries": {"/safe/base/Library/Movies": []},
        }
        plan_proc, _ = self.run_cli(self.resource_args())
        share_ref = self._read_share_ref(plan_proc)
        proc, calls = self.run_cli(
            self.resource_args(share_ref=share_ref) + ["--execute"],
            state=state,
            transfer_name="incoming-folder",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        output = proc.stdout + proc.stderr
        self.assertNotIn(FIXTURE_SHARE_URL, output)
        self.assertNotIn(FIXTURE_PASSWORD, output)
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "transfer", "ls"])
        transfer_argv = calls[-2]
        self.assertEqual(transfer_argv[0], "transfer")
        self.assertEqual(transfer_argv[1], FIXTURE_SHARE_URL)
        self.assertEqual(transfer_argv[2:4], ["-p", FIXTURE_PASSWORD])
        payload = json.loads(proc.stdout)["data"]
        self.assertEqual(payload["share_ref"], share_ref)
        self.assertTrue(payload["executed"])

    def test_resource_id_execute_rejects_candidate_drift_before_bdpan(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            shutil.copytree(FIXTURES, first)
            shutil.copytree(FIXTURES, second)
            changed = (second / "detail.html").read_text(encoding="utf-8").replace(
                FIXTURE_SHARE_URL,
                "https://pan.baidu.example/s/changed-share-90001",
            )
            (second / "detail.html").write_text(changed, encoding="utf-8")
            plan_proc, _ = self.run_cli(self.resource_args(fixture_dir=first))
            share_ref = self._read_share_ref(plan_proc)
            state = {
                "directories": ["/safe/base/Library/Movies"],
                "entries": {"/safe/base/Library/Movies": []},
            }
            proc, calls = self.run_cli(
                self.resource_args(fixture_dir=second, share_ref=share_ref) + ["--execute"],
                state=state,
            )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"]["code"], "INVALID_ARG")
        self.assertIn("changed", payload["error"]["message"])
        self.assertNotIn("share_ref", payload["error"].get("details", {}))
        self.assertNotIn("changed-share-90001", proc.stdout + proc.stderr)
        self.assertEqual(calls, [])

    def test_multiple_resource_links_require_explicit_index_and_redact_candidate_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = self._write_two_candidate_fixture(Path(tmp))
            proc, calls = self.run_cli(self.resource_args(fixture_dir=fixture_dir))
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"]["code"], "INVALID_ARG")
        candidates = payload["error"]["details"]["candidates"]
        self.assertEqual([item["index"] for item in candidates], [0, 1])
        self.assertEqual(candidates[0]["quality"], "1080p.BluRay")
        self.assertEqual(candidates[1]["quality"], "720p")
        for item in candidates:
            self.assertNotIn("url", item)
            self.assertNotIn("password", item)
        self.assertNotIn(FIXTURE_SHARE_URL, proc.stdout + proc.stderr)
        self.assertNotIn(FIXTURE_PASSWORD, proc.stdout + proc.stderr)
        self.assertEqual(calls, [])

    def test_resource_link_index_selects_candidate_without_exposing_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = self._write_two_candidate_fixture(Path(tmp))
            proc, calls = self.run_cli(
                self.resource_args(fixture_dir=fixture_dir, link_index=1)
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls, [])
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["data"]["link_index"], 1)
        self.assertNotIn(FIXTURE_SHARE_URL, proc.stdout + proc.stderr)
        self.assertNotIn(FIXTURE_PASSWORD, proc.stdout + proc.stderr)

    def test_default_emits_plan_without_any_mutating_bdpan_call(self):
        proc, calls = self.run_cli(self.base_args())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["data"]["dest_dir"], "/safe/base/Library/Movies")
        self.assertNotIn("final_folder", payload["data"])
        self.assertTrue(payload["data"]["plan"])
        self.assertNotIn("transfer", [item[0] for item in calls])
        self.assertNotIn("mkdir", [item[0] for item in calls])

    def test_anime_and_webdrama_use_distinct_category_directories(self):
        for resource_type, expected in (("anime", "动漫"), ("webdrama", "网剧")):
            with self.subTest(resource_type=resource_type):
                args = self.base_args()
                args[args.index("--type") + 1] = resource_type
                proc, calls = self.run_cli(args)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                payload = json.loads(proc.stdout)
                self.assertEqual(
                    payload["data"]["dest_dir"],
                    f"/safe/base/Library/{expected}",
                )
                self.assertEqual(calls, [])

    def test_execute_transfers_only_to_configured_base_and_reports_that_directory(self):
        state = {
            "directories": ["/safe/base/Library/Movies"],
            "entries": {"/safe/base/Library/Movies": []},
        }
        proc, calls = self.run_cli(
            self.base_args() + ["--execute"],
            state=state,
            transfer_name="incoming-folder",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "transfer", "ls"])
        transfer_argv = calls[-2]
        self.assertEqual(transfer_argv[-2:], ["-d", "/safe/base/Library/Movies"])
        self.assertEqual(transfer_argv[2:4], ["-p", "qwer"])
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["data"]["dest_dir"], "/safe/base/Library/Movies")
        self.assertEqual(
            payload["data"]["source_dir"],
            "/safe/base/Library/Movies/incoming-folder",
        )
        self.assertTrue(payload["data"]["organize_ready"])
        self.assertEqual(payload["data"]["postcondition"]["status"], "verified")
        self.assertNotIn("qwer", proc.stdout + proc.stderr)

    def test_post_transfer_read_failure_reports_executed_but_unverified_without_retry(self):
        target = "/safe/base/Library/Movies"
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state={"directories": [target], "entries": {target: []}},
            fake_fail="ls:3",
            transfer_name="incoming-folder",
            return_state=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)["data"]
        self.assertTrue(payload["executed"])
        self.assertFalse(payload["organize_ready"])
        self.assertIsNone(payload["source_dir"])
        self.assertEqual(payload["postcondition"]["status"], "unverified")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "transfer", "ls"])
        self.assertIn(
            {"server_filename": "incoming-folder", "isdir": True},
            final_state["entries"][target],
        )

    def test_invalid_extra_post_transfer_entry_prevents_verified_source_dir(self):
        module = _load_transfer_module()
        target = "/safe/base/Library/Movies"
        unsafe_snapshots = (
            [
                {"server_filename": "incoming-folder", "isdir": True},
                {"isdir": True},
            ],
            [{"server_filename": "incoming-folder"}],
            [{"server_filename": "incoming-folder", "isdir": "false"}],
        )
        for after in unsafe_snapshots:
            with self.subTest(after=after):
                with mock.patch.object(module, "_list_dest", return_value=after):
                    result = module._post_transfer_result([], target, mock.sentinel.settings)
                self.assertIsNone(result["source_dir"])
                self.assertFalse(result["organize_ready"])
                self.assertNotEqual(result["status"], "verified")

    def test_invalid_url_id_and_escaped_title_fail_before_fake(self):
        cases = (
            ["--url", "https://evil.example/s/1abcde"],
            ["--url", "https://pan.baidu.com/s/../escape"],
            ["--imdb-id", "bad/id"],
            ["--title-en", "../escape"],
        )
        for replacement in cases:
            with self.subTest(replacement=replacement):
                args = self.base_args()
                args[args.index(replacement[0]) + 1] = replacement[1]
                proc, calls = self.run_cli(args + ["--execute"])
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
                self.assertEqual(calls, [])

    def test_obsolete_auto_organize_flag_is_rejected_before_fake(self):
        proc, calls = self.run_cli(self.base_args() + ["--auto-organize"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])

    def test_plan_and_execute_never_echo_share_url_or_password(self):
        full_url = "https://pan.baidu.com/s/1abcde"
        for extra in ([], ["--execute"]):
            with self.subTest(extra=extra):
                proc, _ = self.run_cli(self.base_args() + extra, state={
                    "directories": ["/safe/base/Library/Movies"],
                    "entries": {"/safe/base/Library/Movies": []},
                })
                self.assertEqual(proc.returncode, 0, proc.stderr)
                output = proc.stdout + proc.stderr
                self.assertNotIn(full_url, output)
                self.assertNotIn("?pwd=", output)
                self.assertNotIn("qwer", output)
                action = json.loads(proc.stdout)["data"]["plan"][0]
                self.assertEqual(action["source"], "baidu-share")
                self.assertNotIn("url", action)

    def test_transfer_failure_does_not_echo_argv_or_change_state(self):
        initial = {
            "directories": ["/safe/base/Library/Movies"],
            "entries": {"/safe/base/Library/Movies": []},
        }
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=initial,
            fake_fail="transfer",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        output = proc.stdout + proc.stderr
        self.assertNotIn("https://pan.baidu.com/s/1abcde", output)
        self.assertNotIn("qwer", output)
        self.assertNotIn("?pwd=", output)
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "transfer"])
        self.assertEqual(final_state, initial)

    def test_transfer_toctou_collision_stops_without_transfer(self):
        target = "/safe/base/Library/Movies"
        injected = "Limitless.{imdb-tt1219289}"
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state={"directories": [target], "entries": {target: []}},
            inject_after_ls=1,
            inject_dir=target,
            inject_name=injected,
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("transfer", [item[0] for item in calls])
        self.assertEqual(
            final_state["entries"][target],
            [{"server_filename": injected, "isdir": False}],
        )

    def test_name_only_collision_is_rejected_before_transfer(self):
        target = "/safe/base/Library/Movies"
        expected = "Limitless.{imdb-tt1219289}"
        proc, calls = self.run_cli(
            self.base_args() + ["--execute"],
            state={
                "directories": [target],
                "entries": {target: [{"name": expected, "isdir": True}]},
            },
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("transfer", [item[0] for item in calls])

    def test_fake_transfer_no_clobber_stops_when_collision_appears_after_fresh_ls(self):
        target = "/safe/base/Library/Movies"
        injected = "Limitless.{imdb-tt1219289}"
        initial = {"directories": [target], "entries": {target: []}}
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=initial,
            inject_after_ls=2,
            inject_dir=target,
            inject_name=injected,
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "transfer"])
        self.assertEqual(
            final_state["entries"][target],
            [{"server_filename": injected, "isdir": False}],
        )

    def test_embedded_share_code_is_redacted_when_fake_failure_echoes_argv(self):
        args = self.base_args()
        password_index = args.index("--password")
        del args[password_index : password_index + 2]
        args[args.index("--url") + 1] = "https://pan.baidu.com/s/1abcde?pwd=abcd"
        target = "/safe/base/Library/Movies"
        proc, calls, final_state = self.run_cli(
            args + ["--execute"],
            state={"directories": [target], "entries": {target: []}},
            fake_fail="transfer",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        output = proc.stdout + proc.stderr
        self.assertNotIn("https://pan.baidu.com/s/1abcde", output)
        self.assertNotIn("abcd", output)
        transfer_argv = calls[-1]
        self.assertEqual(transfer_argv[0], "transfer")
        self.assertEqual(transfer_argv[2:4], ["-p", "abcd"])
        self.assertEqual(final_state, {"directories": [target], "entries": {target: []}})


if __name__ == "__main__":
    unittest.main()
