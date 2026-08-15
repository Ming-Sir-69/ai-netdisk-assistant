from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT = REPO_ROOT / "bin" / "panlib-audit"


def _write_bridge(path: Path) -> None:
    path.write_text(
        '''#!/usr/bin/env python3
import json, os, sys
state = json.loads(open(os.environ["PANLIB_BRIDGE_STATE"], encoding="utf-8").read())
payload = json.loads(sys.stdin.read())
tool = payload["tool"]
args = payload.get("arguments", {})
if tool == "file_list":
    directory = args["dir"]
    if directory in state.get("unreadable", []):
        print(json.dumps({"error": {"code": "INVALID_ARG", "message": "params error"}}))
        raise SystemExit(0)
    print(json.dumps({"list": state["tree"].get(directory, [])}, ensure_ascii=False))
elif tool == "file_keyword_search":
    print(json.dumps({"list": state.get("search", [])}, ensure_ascii=False))
else:
    print(json.dumps({"error": {"code": "INVALID_ARG", "message": "unsupported"}}))
''',
        encoding="utf-8",
    )
    path.chmod(0o755)


class AuditCliTests(unittest.TestCase):
    """一致性校验器：只读扫描，把偏差列成清单，绝不自己动手改。

    它是「批量整理」的第一步——先让人看见要改什么，再决定改不改。
    """

    def run_audit(self, tree: dict, *, unreadable=None, search=None, extra=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        bridge = root / "bridge.py"
        _write_bridge(bridge)
        state = root / "state.json"
        state.write_text(
            json.dumps(
                {"tree": tree, "unreadable": unreadable or [], "search": search or []},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update(
            {
                "PANLIB_MCP_COMMAND": shlex.join([sys.executable, str(bridge)]),
                "PANLIB_BRIDGE_STATE": str(state),
            }
        )
        proc = subprocess.run(
            [sys.executable, str(AUDIT), "--path", "/lib"] + (extra or []),
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        return proc

    @staticmethod
    def entry(name, path, isdir=False, size=1):
        return {"server_filename": name, "path": path, "isdir": isdir, "size": size}

    def findings(self, proc) -> list[dict]:
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["data"]["findings"]

    def test_a_fully_compliant_library_reports_no_findings(self):
        tree = {
            "/lib": [self.entry("A.2020", "/lib/A.2020", isdir=True)],
            "/lib/A.2020": [
                self.entry("A.2020.{imdb-tt1234567}.1080p.mkv", "/lib/A.2020/A.2020.{imdb-tt1234567}.1080p.mkv")
            ],
        }
        self.assertEqual(self.findings(self.run_audit(tree)), [])

    def test_a_video_without_an_imdb_segment_is_reported(self):
        tree = {
            "/lib": [self.entry("A.2020", "/lib/A.2020", isdir=True)],
            "/lib/A.2020": [self.entry("raw.release.group.mkv", "/lib/A.2020/raw.release.group.mkv")],
        }
        findings = self.findings(self.run_audit(tree))
        self.assertEqual([f["issue"] for f in findings], ["unnormalized_filename"])
        self.assertEqual(findings[0]["path"], "/lib/A.2020/raw.release.group.mkv")

    def test_the_none_placeholder_counts_as_normalized(self):
        tree = {
            "/lib": [self.entry("A.1991", "/lib/A.1991", isdir=True)],
            "/lib/A.1991": [self.entry("A.1991.{imdb-none}.mkv", "/lib/A.1991/A.1991.{imdb-none}.mkv")],
        }
        self.assertEqual(self.findings(self.run_audit(tree)), [])

    def test_a_content_node_holding_directories_is_reported(self):
        tree = {
            "/lib": [self.entry("A.2020", "/lib/A.2020", isdir=True)],
            "/lib/A.2020": [self.entry("extra", "/lib/A.2020/extra", isdir=True)],
            "/lib/A.2020/extra": [],
        }
        issues = [f["issue"] for f in self.findings(self.run_audit(tree))]
        self.assertIn("content_node_holds_directories", issues)

    def test_an_empty_container_is_reported_as_residue(self):
        tree = {"/lib": [self.entry("Old.{imdb-tt1}", "/lib/Old.{imdb-tt1}", isdir=True)], "/lib/Old.{imdb-tt1}": []}
        issues = [f["issue"] for f in self.findings(self.run_audit(tree))]
        self.assertIn("empty_container", issues)

    def test_an_unreadable_directory_is_reported_not_silently_skipped(self):
        # 含 & 的路径读不了，但「读不到」必须显式出现在清单里，
        # 否则会被误当成「已检查且合规」。
        tree = {"/lib": [self.entry("Mr.&.Mrs", "/lib/Mr.&.Mrs", isdir=True)]}
        findings = self.findings(self.run_audit(tree, unreadable=["/lib/Mr.&.Mrs"]))
        self.assertEqual([f["issue"] for f in findings], ["unreadable_directory"])

    def test_the_audit_never_issues_a_write_call(self):
        tree = {
            "/lib": [self.entry("A.2020", "/lib/A.2020", isdir=True)],
            "/lib/A.2020": [self.entry("raw.mkv", "/lib/A.2020/raw.mkv")],
        }
        proc = self.run_audit(tree)
        self.assertEqual(json.loads(proc.stdout)["meta"]["mode"], "read-only")


    def test_category_roots_are_containers_not_content_nodes(self):
        # 类别根本来就装目录，且空着不算残留——否则清单会被必然存在的
        # 结构性目录刷屏，真正的问题反而被淹没。
        tree = {
            "/lib": [
                self.entry("Movies", "/lib/Movies", isdir=True),
                self.entry("Documentary", "/lib/Documentary", isdir=True),
            ],
            "/lib/Movies": [self.entry("A.2020", "/lib/Movies/A.2020", isdir=True)],
            "/lib/Movies/A.2020": [
                self.entry("A.2020.{imdb-tt1234567}.mkv", "/lib/Movies/A.2020/A.2020.{imdb-tt1234567}.mkv")
            ],
            "/lib/Documentary": [],
        }
        self.assertEqual(self.findings(self.run_audit(tree)), [])


if __name__ == "__main__":
    unittest.main()
