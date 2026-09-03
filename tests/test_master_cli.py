"""panlib-master：母版发行史判定的行为测试。

这些用例存在的理由不是覆盖率，而是三条实测教训的回归锁：
1. 真实措辞里 4K 和 2K 经常同句出现（"4K UHD upscaled from the 2K DI"），
   天真地取第一个/最大的数字会得出与事实相反的结论；
2. 证据源互相冲突时自动取最大值 = 悄悄选了可能错的一方，必须停机；
3. BLOCKED 必须非零退出且走 emit_error——emit_success 硬编码 exit 0，
   走它会让脚本化调用把「需要人裁决」读成「判定成功」。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MASTER = REPO_ROOT / "bin" / "panlib-master"
PY = sys.executable


class MasterCliTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # 台账路径由 SKILL_ROOT 决定，测试用独立 runtime 目录隔离，
        # 避免污染真实台账、也避免真实台账让测试结果随环境漂移。
        self.ledger = Path(tmp.name) / "master_lookup.jsonl"

    def run_cli(self, *args: str):
        proc = subprocess.run(
            [PY, str(MASTER), *args],
            capture_output=True, text=True, cwd=REPO_ROOT,
            env={"PANLIB_MASTER_LEDGER": str(self.ledger), "PATH": "/usr/bin:/bin"},
        )
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return proc.returncode, payload

    def record(self, title: str, year: str, source: str, evidence: str | None):
        args = ["record", "--title", title, "--year", year, "--source", source]
        args += ["--evidence", evidence] if evidence else ["--no-evidence"]
        return self.run_cli(*args)

    def verdict(self, title: str, year: str):
        return self.run_cli("verdict", "--title", title, "--year", year)

    # --- 前置状态 -----------------------------------------------------

    def test_verdict_without_any_record_is_not_queried_and_exits_nonzero(self):
        code, payload = self.verdict("Nothing", "2000")
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["details"]["status"], "NOT_QUERIED")

    def test_query_then_cache_prevents_a_second_search_round(self):
        code, first = self.run_cli("query", "--title", "Cached", "--year", "2000")
        self.assertEqual(code, 0)
        self.assertEqual(first["data"]["status"], "NEEDS_QUERY")

        self.record("Cached", "2000", "wikipedia", None)

        code, second = self.run_cli("query", "--title", "Cached", "--year", "2000")
        self.assertEqual(code, 0)
        self.assertEqual(second["data"]["status"], "CACHED")

    # --- 证据句解析：真实措辞的对抗用例 --------------------------------

    def test_upscale_wording_resolves_to_the_lower_native_cap_not_the_higher(self):
        """真实反例：'4K UHD upscaled from the original 2K DI'。

        句中 4K 是算出来的、2K 才是拍出来的。取最大值会把它误判成值得追 4K。
        """
        _, rec = self.record(
            "Upscale Trap", "2000", "dvdbeaver",
            "This 4K UHD release was upscaled from the original 2K digital intermediate",
        )
        self.assertEqual(rec["data"]["event"]["resolution_hint"], "2K")
        self.assertTrue(rec["data"]["event"]["upscale_marker"])

        code, verdict = self.verdict("Upscale Trap", "2000")
        self.assertEqual(code, 0)
        self.assertEqual(verdict["data"]["status"], "NATIVE_CAP_2K")

    def test_plain_upscale_claim_from_1080p_master_is_not_a_4k_verdict(self):
        _, rec = self.record(
            "Upscale Trap 2", "2000", "dvdbeaver",
            "Upscaled to 4K from a 1080p master",
        )
        self.assertTrue(rec["data"]["event"]["upscale_marker"])
        _, verdict = self.verdict("Upscale Trap 2", "2000")
        self.assertNotEqual(verdict["data"]["status"], "NATIVE_CAP_4K")

    def test_genuine_native_scan_still_resolves_to_4k(self):
        self.record("Real 4K", "2020", "dvdbeaver",
                    "New 4K scan of the original camera negative")
        code, verdict = self.verdict("Real 4K", "2020")
        self.assertEqual(code, 0)
        self.assertEqual(verdict["data"]["status"], "NATIVE_CAP_4K")

    def test_progressive_wording_without_upscale_marker_takes_the_higher_number(self):
        """'2K DI 之后又做了 4K 扫描' 这类递进描述，上限确实是 4K。"""
        self.record("Progressive", "2010", "dvdbeaver",
                    "The old 2K transfer was replaced by a new 4K restoration")
        _, verdict = self.verdict("Progressive", "2010")
        self.assertEqual(verdict["data"]["status"], "NATIVE_CAP_4K")

    # --- 冲突与保守停机 ------------------------------------------------

    def test_conflicting_sources_block_instead_of_silently_taking_the_max(self):
        self.record("Conflict", "2000", "dvdbeaver", "restored in 2K")
        self.record("Conflict", "2000", "bluray_com", "new 4K scan")

        code, payload = self.verdict("Conflict", "2000")
        self.assertNotEqual(code, 0, "冲突必须非零退出，否则脚本会把它读成判定成功")
        details = payload["error"]["details"]
        self.assertEqual(details["status"], "CONFLICTING_EVIDENCE")
        self.assertEqual(details["native_caps_by_source"],
                         {"dvdbeaver": 2, "bluray_com": 4})

    def test_agreeing_sources_do_not_trigger_the_conflict_path(self):
        self.record("Agree", "2000", "dvdbeaver", "restored in 2K")
        self.record("Agree", "2000", "bluray_com", "2K digital transfer")
        code, verdict = self.verdict("Agree", "2000")
        self.assertEqual(code, 0)
        self.assertEqual(verdict["data"]["status"], "NATIVE_CAP_2K")

    def test_searched_but_no_resolution_evidence_is_conservative_not_a_guess(self):
        self.record("Silent", "2000", "dvdbeaver", None)
        self.record("Silent", "2000", "wikipedia", None)
        code, verdict = self.verdict("Silent", "2000")
        self.assertEqual(code, 0)
        self.assertEqual(verdict["data"]["status"], "UNKNOWN_CONSERVATIVE")

    def test_record_requires_an_explicit_evidence_decision(self):
        """既不给 --evidence 也不给 --no-evidence 时必须拒绝。

        否则「查过但没证据」和「忘了记录」在台账里无法区分。
        """
        code, payload = self.run_cli(
            "record", "--title", "X", "--year", "2000", "--source", "wikipedia")
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "INVALID_ARG")

    def test_ledger_is_isolated_by_env_var(self):
        """台账路径可被环境变量重定向——测试与真实数据不能共用一个文件。"""
        self.record("Isolated", "2000", "wikipedia", None)
        self.assertTrue(self.ledger.is_file())
        rows = [json.loads(x) for x in self.ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertEqual(rows[0]["title"], "Isolated")


if __name__ == "__main__":
    unittest.main()
