from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX = REPO_ROOT / "bin" / "panlib-sandbox"
FAKE = REPO_ROOT / "tests" / "fakes" / "bdpan"

BASE = "/safe/base"
SANDBOX_ROOT = f"{BASE}/_沙盒_规范验证"
LIBRARY = f"{BASE}/Library"


class SandboxCliTests(unittest.TestCase):
    """panlib-sandbox 是唯一允许的复制入口，且只能写入沙盒根。

    它存在的唯一目的是在真实网盘里搭一个与片库物理隔离的验证环境，
    因此「拒绝写到沙盒外」比「能不能复制成功」更重要。
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
            }
        )
        if fake_fail:
            env["BDPAN_FAKE_FAIL"] = fake_fail
        proc = subprocess.run(
            [sys.executable, str(SANDBOX)] + extra,
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        calls = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
        return proc, calls

    def base_state(self) -> dict:
        return {
            "directories": [LIBRARY, f"{LIBRARY}/Movies", SANDBOX_ROOT],
            "entries": {
                f"{LIBRARY}/Movies": [
                    {"server_filename": "样本.mkv", "isdir": False},
                ],
                SANDBOX_ROOT: [],
                LIBRARY: [{"server_filename": "Movies", "isdir": True}],
            },
        }

    def test_plan_only_returns_plan_ref_and_never_copies(self):
        proc, calls = self.run_cli(
            [
                "copy",
                "--source",
                f"{LIBRARY}/Movies/样本.mkv",
                "--dest-dir",
                SANDBOX_ROOT,
            ],
            state=self.base_state(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["meta"]["mode"], "plan-only")
        self.assertRegex(payload["data"]["plan_ref"], r"^[0-9a-f]{64}$")
        self.assertTrue(payload["data"]["execute_required"])
        self.assertNotIn("cp", [call[0] for call in calls])

    def test_execute_requires_a_matching_plan_ref(self):
        proc, calls = self.run_cli(
            [
                "copy",
                "--source",
                f"{LIBRARY}/Movies/样本.mkv",
                "--dest-dir",
                SANDBOX_ROOT,
                "--execute",
            ],
            state=self.base_state(),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("cp", [call[0] for call in calls])

    def test_destination_outside_the_sandbox_root_is_refused_before_bdpan(self):
        for dest in (LIBRARY, f"{LIBRARY}/Movies", BASE, f"{SANDBOX_ROOT}/../Library"):
            with self.subTest(dest=dest):
                proc, calls = self.run_cli(
                    [
                        "copy",
                        "--source",
                        f"{LIBRARY}/Movies/样本.mkv",
                        "--dest-dir",
                        dest,
                    ],
                    state=self.base_state(),
                )
                self.assertNotEqual(proc.returncode, 0)
                code = json.loads(proc.stdout)["error"]["code"]
                self.assertIn(code, {"PERMISSION", "INVALID_ARG"})
                self.assertEqual(calls, [])

    def test_source_escaping_the_configured_base_is_rejected(self):
        proc, calls = self.run_cli(
            ["copy", "--source", "/elsewhere/样本.mkv", "--dest-dir", SANDBOX_ROOT],
            state=self.base_state(),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])

    def test_execute_copies_then_verifies_the_destination(self):
        plan, _ = self.run_cli(
            [
                "copy",
                "--source",
                f"{LIBRARY}/Movies/样本.mkv",
                "--dest-dir",
                SANDBOX_ROOT,
            ],
            state=self.base_state(),
        )
        plan_ref = json.loads(plan.stdout)["data"]["plan_ref"]
        proc, calls = self.run_cli(
            [
                "copy",
                "--source",
                f"{LIBRARY}/Movies/样本.mkv",
                "--dest-dir",
                SANDBOX_ROOT,
                "--execute",
                "--plan-ref",
                plan_ref,
            ],
            state=self.base_state(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["data"]["executed"])
        self.assertEqual(payload["data"]["postcondition"]["status"], "verified")
        self.assertIn("cp", [call[0] for call in calls])

    def test_copy_failure_is_reported_without_claiming_success(self):
        plan, _ = self.run_cli(
            [
                "copy",
                "--source",
                f"{LIBRARY}/Movies/样本.mkv",
                "--dest-dir",
                SANDBOX_ROOT,
            ],
            state=self.base_state(),
        )
        plan_ref = json.loads(plan.stdout)["data"]["plan_ref"]
        proc, _ = self.run_cli(
            [
                "copy",
                "--source",
                f"{LIBRARY}/Movies/样本.mkv",
                "--dest-dir",
                SANDBOX_ROOT,
                "--execute",
                "--plan-ref",
                plan_ref,
            ],
            state=self.base_state(),
            fake_fail="cp",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error", json.loads(proc.stdout))


class SandboxMkdirTests(SandboxCliTests):
    def test_mkdir_outside_the_sandbox_root_is_refused_before_bdpan(self):
        for target in (LIBRARY, f"{LIBRARY}/Movies", f"{BASE}/其他"):
            with self.subTest(target=target):
                proc, calls = self.run_cli(
                    ["mkdir", "--path", target], state=self.base_state()
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(json.loads(proc.stdout)["error"]["code"], "PERMISSION")
                self.assertEqual(calls, [])

    def test_mkdir_plan_then_execute_creates_and_verifies(self):
        target = f"{SANDBOX_ROOT}/形态样本"
        plan, calls = self.run_cli(["mkdir", "--path", target], state=self.base_state())
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertEqual(json.loads(plan.stdout)["meta"]["mode"], "plan-only")
        self.assertEqual(calls, [])
        proc, calls = self.run_cli(
            ["mkdir", "--path", target, "--execute"], state=self.base_state()
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["data"]["executed"])
        self.assertEqual(payload["data"]["postcondition"]["status"], "verified")
        self.assertIn("mkdir", [call[0] for call in calls])


if __name__ == "__main__":
    unittest.main()
