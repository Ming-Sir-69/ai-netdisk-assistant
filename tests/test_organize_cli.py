from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ORGANIZE = REPO_ROOT / "bin" / "panlib-organize"
FAKE = REPO_ROOT / "tests" / "fakes" / "bdpan"


class OrganizeCliTests(unittest.TestCase):
    def run_cli(
        self,
        extra: list[str],
        *,
        state: dict,
        fake_fail: str = "",
        inject_after_ls: int | None = None,
        inject_before: str = "",
        inject_dir: str = "",
        inject_name: str = "",
        return_state: bool = False,
    ):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        log = root / "calls.json"
        state_path = root / "state.json"
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
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
        if inject_before:
            env["BDPAN_FAKE_INJECT_BEFORE"] = inject_before
            env["BDPAN_FAKE_INJECT_DIR"] = inject_dir
            env["BDPAN_FAKE_INJECT_NAME"] = inject_name
        proc = subprocess.run(
            [sys.executable, str(ORGANIZE)] + extra,
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
            "--source-dir",
            "/safe/base/Library/Movies/incoming",
            "--target-dir",
            "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}",
            "--title-en",
            "Limitless",
            "--imdb-id",
            "tt1219289",
            "--year",
            "2011",
            "--quality",
            "1080p",
            "--mode",
            "tv",
        ]

    def episode_state(self):
        return {
            "directories": [
                "/safe/base/Library/Movies/incoming",
                "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}",
            ],
            "entries": {
                "/safe/base/Library/Movies/incoming": [
                    {"server_filename": "Limitless.S01E01.mkv", "isdir": False},
                    {"server_filename": "Limitless.S01E02.mkv", "isdir": False},
                ],
                "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}": [],
            },
        }

    def test_default_plan_has_distinct_episode_targets_and_no_mutation(self):
        proc, calls = self.run_cli(self.base_args(), state=self.episode_state())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        actions = payload["data"]["actions"]
        renames = [item for item in actions if item["action"] == "rename"]
        self.assertEqual([item["new_name"] for item in renames], [
            "Limitless.S01E01.{imdb-tt1219289}.1080p.mkv",
            "Limitless.S01E02.{imdb-tt1219289}.1080p.mkv",
        ])
        self.assertEqual([item[0] for item in calls], ["ls", "ls"])
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertNotIn("rename", [item[0] for item in calls])
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_execute_orders_mkdir_mv_then_rename_and_never_removes_by_default(self):
        state = self.episode_state()
        state["directories"].remove("/safe/base/Library/Movies/Limitless.{imdb-tt1219289}")
        state["entries"].pop("/safe/base/Library/Movies/Limitless.{imdb-tt1219289}")
        proc, calls = self.run_cli(self.base_args() + ["--execute"], state=state)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([item[0] for item in calls], [
            "ls", "ls", "ls", "mkdir", "ls", "mv", "ls", "rename",
            "ls", "mv", "ls", "rename",
        ])
        self.assertEqual(calls[5][2], "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}")
        self.assertEqual(calls[7][0:2], ["rename", "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}/Limitless.S01E01.mkv"])
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_unknown_episode_fails_before_any_mutation(self):
        state = self.episode_state()
        state["entries"]["/safe/base/Library/Movies/incoming"] = [
            {"server_filename": "Limitless.release.mkv", "isdir": False}
        ]
        proc, calls = self.run_cli(self.base_args() + ["--execute"], state=state)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls"])

    def test_failed_mv_stops_and_never_removes_source(self):
        initial = self.episode_state()
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute", "--remove-empty-source"],
            state=initial,
            fake_fail="mv:1",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        error = json.loads(proc.stdout)["error"]
        self.assertEqual(error["code"], "NETWORK")
        self.assertEqual(error["details"]["failed_action"]["action"], "mv")
        self.assertEqual(error["details"]["completed"], [])
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "mv"])
        self.assertNotIn("rm", [item[0] for item in calls])
        self.assertEqual(final_state, initial)

    def test_failed_rename_stops_before_next_file_and_never_removes_source(self):
        initial = self.episode_state()
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute", "--remove-empty-source"],
            state=initial,
            fake_fail="rename:1",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        error = json.loads(proc.stdout)["error"]
        self.assertEqual(error["code"], "NETWORK")
        self.assertEqual(error["details"]["failed_action"]["action"], "rename")
        self.assertEqual(
            [item["action"] for item in error["details"]["completed"]],
            ["mv"],
        )
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "mv", "ls", "rename"])
        self.assertNotIn("rm", [item[0] for item in calls])
        self.assertEqual(
            final_state["entries"]["/safe/base/Library/Movies/incoming"],
            [{"server_filename": "Limitless.S01E02.mkv", "isdir": False}],
        )
        self.assertEqual(
            final_state["entries"]["/safe/base/Library/Movies/Limitless.{imdb-tt1219289}"],
            [{"server_filename": "Limitless.S01E01.mkv", "isdir": False}],
        )

    def test_remove_empty_source_checks_again_then_removes(self):
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute", "--remove-empty-source"],
            state=self.episode_state(),
            return_state=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([item[0] for item in calls], [
            "ls", "ls", "ls", "mv", "ls", "rename", "ls", "mv",
            "ls", "rename", "ls", "rm",
        ])
        cleanup = json.loads(proc.stdout)["data"]["cleanup"]
        self.assertEqual(cleanup, {
            "requested": True,
            "verified_empty": True,
            "removed": True,
        })
        self.assertNotIn("/safe/base/Library/Movies/incoming", final_state["entries"])
        self.assertNotIn("/safe/base/Library/Movies/incoming", final_state["directories"])

    def test_nested_discovery_is_explicit_and_recursive(self):
        state = {
            "directories": [
                "/safe/base/Library/Movies/incoming",
                "/safe/base/Library/Movies/incoming/part-1",
                "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}",
            ],
            "entries": {
                "/safe/base/Library/Movies/incoming": [
                    {"server_filename": "part-1", "isdir": True}
                ],
                "/safe/base/Library/Movies/incoming/part-1": [
                    {"server_filename": "Limitless.S01E01.mkv", "isdir": False}
                ],
                "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}": [],
            },
        }
        proc, calls = self.run_cli(self.base_args() + ["--depth", "2"], state=state)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(["ls", "/safe/base/Library/Movies/incoming/part-1", "--json"], calls)
        actions = json.loads(proc.stdout)["data"]["actions"]
        self.assertEqual(actions[-2]["from"], "/safe/base/Library/Movies/incoming/part-1/Limitless.S01E01.mkv")

    def test_target_source_basename_collision_fails_before_any_mutation(self):
        state = self.episode_state()
        state["entries"]["/safe/base/Library/Movies/Limitless.{imdb-tt1219289}"] = [
            {"server_filename": "Limitless.S01E01.mkv", "isdir": False}
        ]
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute", "--remove-empty-source"],
            state=state,
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls"])
        self.assertEqual(final_state, state)

    def test_target_file_type_mismatch_fails_before_any_mutation(self):
        state = self.episode_state()
        target = "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}"
        parent = "/safe/base/Library/Movies"
        state["directories"].remove(target)
        state["entries"].pop(target)
        state["entries"].setdefault(parent, [])
        state["entries"][parent].append(
            {"server_filename": "Limitless.{imdb-tt1219289}", "isdir": False}
        )
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"], state=state, return_state=True
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls"])
        self.assertEqual(final_state, state)

    def test_successful_execute_persists_expected_fake_state(self):
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"], state=self.episode_state(), return_state=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        source_entries = final_state["entries"]["/safe/base/Library/Movies/incoming"]
        target_entries = final_state["entries"]["/safe/base/Library/Movies/Limitless.{imdb-tt1219289}"]
        self.assertEqual(source_entries, [])
        self.assertEqual(
            sorted(item["server_filename"] for item in target_entries),
            [
                "Limitless.S01E01.{imdb-tt1219289}.1080p.mkv",
                "Limitless.S01E02.{imdb-tt1219289}.1080p.mkv",
            ],
        )
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_preflight_toctou_target_collision_stops_before_mutation(self):
        target = "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}"
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=self.episode_state(),
            inject_after_ls=2,
            inject_dir=target,
            inject_name="Limitless.S01E01.{imdb-tt1219289}.1080p.mkv",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertNotIn("rename", [item[0] for item in calls])
        self.assertNotIn("rm", [item[0] for item in calls])
        self.assertEqual(
            final_state["entries"][target],
            [{"server_filename": "Limitless.S01E01.{imdb-tt1219289}.1080p.mkv", "isdir": False}],
        )

    def test_fake_mv_no_clobber_stops_when_collision_appears_after_fresh_ls(self):
        target = "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}"
        initial = self.episode_state()
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=initial,
            inject_after_ls=3,
            inject_dir=target,
            inject_name="Limitless.S01E01.mkv",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "mv"])
        self.assertEqual(final_state["entries"][target], [
            {"server_filename": "Limitless.S01E01.mkv", "isdir": False}
        ])
        self.assertEqual(final_state["entries"]["/safe/base/Library/Movies/incoming"], initial["entries"]["/safe/base/Library/Movies/incoming"])

    def test_fake_rename_no_clobber_stops_when_collision_appears_after_fresh_ls(self):
        target = "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}"
        injected = "Limitless.S01E01.{imdb-tt1219289}.1080p.mkv"
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=self.episode_state(),
            inject_after_ls=4,
            inject_dir=target,
            inject_name=injected,
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "mv", "ls", "rename"])
        self.assertEqual(
            sorted(item["server_filename"] for item in final_state["entries"][target]),
            sorted(["Limitless.S01E01.mkv", injected]),
        )

    def test_fake_mkdir_no_clobber_stops_when_target_file_appears_before_mkdir(self):
        target = "/safe/base/Library/Movies/Limitless.{imdb-tt1219289}"
        parent = "/safe/base/Library/Movies"
        initial = self.episode_state()
        initial["directories"].remove(target)
        initial["entries"].pop(target)
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=initial,
            inject_before="mkdir",
            inject_dir=parent,
            inject_name="Limitless.{imdb-tt1219289}",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "mkdir"])
        self.assertNotIn(target, final_state["directories"])
        self.assertEqual(
            final_state["entries"][parent],
            [{"server_filename": "Limitless.{imdb-tt1219289}", "isdir": False}],
        )


if __name__ == "__main__":
    unittest.main()
