from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTAINER = REPO_ROOT / "bin" / "panlib-container"
FAKE = REPO_ROOT / "tests" / "fakes" / "bdpan"

BASE = "/safe/base"
LIB = f"{BASE}/Library"


class ContainerRenameTests(unittest.TestCase):
    """容器改名：把 `Loki` 变成 `Loki.{series}` 这类纯结构修正。

    存在的理由是代价：不加这个入口，就只能靠搬走目录里的每一个文件来间接
    改名——上百次写操作换一次结构修正，失败面大得多。因此这里只做一件事，
    且做得极窄：**同一个父目录内、只改名字、不移动、不合并、不覆盖**。
    """

    def run_cli(self, extra: list[str], *, state: dict, fake_fail: str = ""):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        log = root / "calls.json"
        state_path = root / "state.json"
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "BDPAN_BIN": str(FAKE),
                "BDPAN_BASE": BASE,
                "BDPAN_LIB": "Library",
                "BDPAN_FAKE_LOG": str(log),
                "BDPAN_FAKE_STATE": str(state_path),
                "PANLIB_JOURNAL_PATH": str(root / "journal.jsonl"),
            }
        )
        if fake_fail:
            env["BDPAN_FAKE_FAIL"] = fake_fail
        proc = subprocess.run(
            [sys.executable, str(CONTAINER)] + extra,
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        calls = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
        return proc, calls, json.loads(state_path.read_text(encoding="utf-8"))

    def state(self) -> dict:
        return {
            "directories": [LIB, f"{LIB}/TV", f"{LIB}/TV/Loki", f"{LIB}/TV/Loki/Loki.S01"],
            "entries": {
                f"{LIB}/TV": [{"server_filename": "Loki", "isdir": True}],
                f"{LIB}/TV/Loki": [{"server_filename": "Loki.S01", "isdir": True}],
                f"{LIB}/TV/Loki/Loki.S01": [
                    {"server_filename": "Loki.S01E01.{imdb-tt1286039}.mkv", "isdir": False}
                ],
            },
        }

    def test_plan_only_binds_a_ref_and_touches_nothing(self):
        proc, calls, _ = self.run_cli(
            ["rename", "--path", f"{LIB}/TV/Loki", "--new-name", "Loki.{series}"],
            state=self.state(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["meta"]["mode"], "plan-only")
        self.assertRegex(payload["data"]["plan_ref"], r"^[0-9a-f]{64}$")
        self.assertNotIn("rename", [call[0] for call in calls])

    def test_execute_renames_in_place_and_verifies(self):
        plan, _, _ = self.run_cli(
            ["rename", "--path", f"{LIB}/TV/Loki", "--new-name", "Loki.{series}"],
            state=self.state(),
        )
        ref = json.loads(plan.stdout)["data"]["plan_ref"]
        proc, calls, final = self.run_cli(
            [
                "rename", "--path", f"{LIB}/TV/Loki", "--new-name", "Loki.{series}",
                "--execute", "--plan-ref", ref,
            ],
            state=self.state(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["data"]["executed"])
        self.assertEqual(payload["data"]["postcondition"]["status"], "verified")
        names = {item["server_filename"] for item in final["entries"][f"{LIB}/TV"]}
        self.assertEqual(names, {"Loki.{series}"})

    def test_execute_without_a_matching_plan_ref_is_refused(self):
        proc, calls, _ = self.run_cli(
            [
                "rename", "--path", f"{LIB}/TV/Loki", "--new-name", "Loki.{series}",
                "--execute", "--plan-ref", "0" * 64,
            ],
            state=self.state(),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("rename", [call[0] for call in calls])

    def test_a_name_that_already_exists_is_refused_before_writing(self):
        state = self.state()
        state["entries"][f"{LIB}/TV"].append({"server_filename": "Loki.{series}", "isdir": True})
        proc, calls, _ = self.run_cli(
            ["rename", "--path", f"{LIB}/TV/Loki", "--new-name", "Loki.{series}"],
            state=state,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        # 读父目录是必要的前置检查；关键是没有发生任何写操作。
        self.assertNotIn("rename", [call[0] for call in calls])

    def test_a_new_name_that_is_a_path_is_refused(self):
        for bad in ("../escape", "a/b", "", "."):
            with self.subTest(bad=bad):
                proc, calls, _ = self.run_cli(
                    ["rename", "--path", f"{LIB}/TV/Loki", "--new-name", bad],
                    state=self.state(),
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(calls, [])

    def test_a_path_outside_the_library_is_refused(self):
        proc, calls, _ = self.run_cli(
            ["rename", "--path", "/elsewhere/Loki", "--new-name", "Loki.{series}"],
            state=self.state(),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])

    def test_a_missing_source_is_reported_as_not_found(self):
        proc, _, _ = self.run_cli(
            ["rename", "--path", f"{LIB}/TV/Missing", "--new-name", "Missing.{series}"],
            state=self.state(),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "NOT_FOUND")

    def test_a_failed_rename_is_not_reported_as_success(self):
        plan, _, _ = self.run_cli(
            ["rename", "--path", f"{LIB}/TV/Loki", "--new-name", "Loki.{series}"],
            state=self.state(),
        )
        ref = json.loads(plan.stdout)["data"]["plan_ref"]
        proc, _, final = self.run_cli(
            [
                "rename", "--path", f"{LIB}/TV/Loki", "--new-name", "Loki.{series}",
                "--execute", "--plan-ref", ref,
            ],
            state=self.state(),
            fake_fail="rename",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error", json.loads(proc.stdout))
        names = {item["server_filename"] for item in final["entries"][f"{LIB}/TV"]}
        self.assertEqual(names, {"Loki"})


if __name__ == "__main__":
    unittest.main()
