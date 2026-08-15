from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from panlib import journal


class JournalTests(unittest.TestCase):
    """恢复台账：出事之后凭什么知道文件原来在哪。

    它是 Agent→Agent 的凭据，不面向用户展示；因此比"好看"更重要的是
    **每条写入事件都能独立回答：源在哪、目标在哪、写完了没有**。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "journal.jsonl"

    def event(self, **overrides) -> dict:
        base = {
            "run_id": "run-1",
            "stage": "organize",
            "attempt": 1,
            "source_path": "/apps/bdpan/片库/Movies/incoming/a.mkv",
            "target_path": "/apps/bdpan/片库/Movies/A.2020/A.2020.{imdb-tt1}.mkv",
            "identity": {"name": "a.mkv", "fsid": "1", "size": 10},
            "plan_ref": "a" * 64,
            "status": "executed",
            "completed_actions": 2,
            "postcondition": "verified",
            "recovery_read_paths": ["/apps/bdpan/片库/Movies/A.2020"],
        }
        base.update(overrides)
        return base

    def test_each_append_is_one_self_contained_json_line(self):
        journal.append_event(self.event(), path=self.path)
        journal.append_event(self.event(attempt=2), path=self.path)
        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            record = json.loads(line)
            self.assertEqual(record["run_id"], "run-1")
            self.assertIn("recorded_at", record)

    def test_missing_required_fields_are_refused(self):
        for missing in ("run_id", "stage", "source_path", "status"):
            with self.subTest(missing=missing):
                event = self.event()
                del event[missing]
                with self.assertRaises(ValueError):
                    journal.append_event(event, path=self.path)
        self.assertFalse(self.path.exists())

    def test_failure_events_need_a_decision_code_and_a_single_next_action(self):
        # 失败事件必须同时带恢复决策码、CLI 原始状态和唯一下一步，
        # 缺一不可——否则下一个 Agent 只能猜。
        incomplete = self.event(status="partial", failed_action="mv")
        with self.assertRaises(ValueError):
            journal.append_event(incomplete, path=self.path)
        complete = self.event(
            status="partial",
            failed_action="mv",
            error_code="RCV-002",
            original_cli_code="NETWORK",
            next_action="read_recovery_paths_and_replan",
        )
        journal.append_event(complete, path=self.path)
        self.assertEqual(len(self.path.read_text(encoding="utf-8").strip().splitlines()), 1)

    def test_unknown_recovery_codes_are_refused(self):
        with self.assertRaises(ValueError):
            journal.append_event(
                self.event(
                    status="partial",
                    error_code="RCV-999",
                    original_cli_code="NETWORK",
                    next_action="read_recovery_paths_and_replan",
                ),
                path=self.path,
            )

    def test_credentials_never_reach_the_journal(self):
        journal.append_event(
            self.event(
                note="url=https://pan.baidu.com/s/1abcdefg pwd=ab12 access_token=xyz"
            ),
            path=self.path,
        )
        text = self.path.read_text(encoding="utf-8")
        for secret in ("pan.baidu.com/s/1abcdefg", "ab12", "xyz"):
            self.assertNotIn(secret, text)

    def test_reading_back_a_run_returns_events_in_order(self):
        journal.append_event(self.event(stage="transfer"), path=self.path)
        journal.append_event(self.event(stage="organize"), path=self.path)
        journal.append_event(self.event(run_id="run-2", stage="archive"), path=self.path)
        events = journal.read_run("run-1", path=self.path)
        self.assertEqual([item["stage"] for item in events], ["transfer", "organize"])

    def test_reading_a_missing_journal_reports_the_recovery_code(self):
        with self.assertRaises(journal.JournalError) as ctx:
            journal.read_run("run-1", path=self.path)
        self.assertEqual(ctx.exception.error_code, "JRN-001")
        self.assertEqual(ctx.exception.next_action, "bounded_relocate")

    def test_corrupt_journal_is_not_silently_skipped(self):
        journal.append_event(self.event(), path=self.path)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
        with self.assertRaises(journal.JournalError) as ctx:
            journal.read_run("run-1", path=self.path)
        self.assertEqual(ctx.exception.error_code, "JRN-002")
        self.assertEqual(ctx.exception.next_action, "stop_journal_invalid")

    def test_run_ids_are_unique_and_carry_no_personal_data(self):
        first, second = journal.new_run_id(), journal.new_run_id()
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{32}$")

    def test_default_path_comes_from_the_environment(self):
        target = Path(self.tmp.name) / "nested" / "custom.jsonl"
        with mock.patch.dict(
            os.environ, {"PANLIB_JOURNAL_PATH": str(target)}, clear=False
        ):
            journal.append_event(self.event())
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
