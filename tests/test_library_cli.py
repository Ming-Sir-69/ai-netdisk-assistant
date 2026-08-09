from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from panlib.mcp_client import MCPBridge, MCPBridgeError, normalize_entries


REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY = REPO_ROOT / "bin" / "panlib-library"


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_bridge(path: Path) -> None:
    body = '''#!/usr/bin/env python3
import json
import os
import sys

state_path = os.environ["PANLIB_BRIDGE_STATE"]
calls_path = os.environ["PANLIB_BRIDGE_CALLS"]
state = json.loads(open(state_path, encoding="utf-8").read())
payload = json.loads(sys.stdin.read())
calls = json.loads(open(calls_path, encoding="utf-8").read()) if os.path.exists(calls_path) else []
calls.append(payload)
open(calls_path, "w", encoding="utf-8").write(json.dumps(calls, ensure_ascii=False))
tool = payload["tool"]
args = payload.get("arguments", {})

if tool == "auth_status":
    print(json.dumps({"status": "ready"}))
elif tool == "file_list":
    directory = args["dir"]
    if directory in ("/apps/bdpan/片库/Movies", "/我的资源/Movies"):
        print(json.dumps({"list": state["source_items"]}, ensure_ascii=False))
    elif directory == "/我的资源/_已归档_待删除":
        print(json.dumps({"list": state["archive_items"]}, ensure_ascii=False))
    elif directory == "/":
        print(json.dumps({"list": [{"fsid": "root-1", "name": "我的资源", "isdir": True}]}, ensure_ascii=False))
    else:
        print(json.dumps({"list": []}, ensure_ascii=False))
elif tool == "file_keyword_search":
    if args.get("key") in {"旧资源", "旧资源_旧版_待删除"}:
        print(json.dumps({"list": state.get("search_items", [])}, ensure_ascii=False))
    else:
        print(json.dumps({"list": [{"fsid": "search-1", "name": "云中漫步", "path": "/我的资源/Movies/云中漫步"}]}, ensure_ascii=False))
elif tool == "file_meta":
    print(json.dumps({"fsid": args.get("fsid", "src-1"), "name": "旧资源", "isdir": True, "size": 123}, ensure_ascii=False))
elif tool == "file_move":
    if not isinstance(args.get("filelist"), str):
        print(json.dumps({"error": {"code": "INVALID_ARG", "message": "filelist must be JSON string"}}))
        raise SystemExit(0)
    move = json.loads(args["filelist"])[0]
    source = next(item for item in state["source_items"] if item["path"] == move["path"])
    state["source_items"].remove(source)
    moved = dict(source)
    moved["path"] = move["dest"].rstrip("/") + "/" + move["newname"]
    moved["name"] = move["newname"]
    state["archive_items"].append(moved)
    open(state_path, "w", encoding="utf-8").write(json.dumps(state, ensure_ascii=False))
    print(json.dumps({"ok": True}))
else:
    print(json.dumps({"error": {"code": "INVALID_ARG", "message": "unsupported tool"}}))
'''
    _executable(path, body)


class LibraryCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bridge = self.root / "bridge.py"
        self.state = self.root / "state.json"
        self.calls = self.root / "calls.json"
        _write_bridge(self.bridge)
        self.state.write_text(
            json.dumps(
                {
                    "source_items": [
                        {
                            "fsid": "src-1",
                            "name": "旧资源",
                            "path": "/apps/bdpan/片库/Movies/旧资源",
                            "isdir": True,
                            "size": 123,
                        }
                    ],
                    "archive_items": [],
                    "search_items": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.calls.write_text("[]", encoding="utf-8")
        self.security = self.root / "security"
        _executable(
            self.security,
            "#!/bin/sh\nif [ \"$1\" = find-generic-password ]; then printf 'secret-token\\n'; fi\n",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalize_entries_infers_category_six_zero_size_as_directory(self):
        entries = normalize_entries(
            {
                "list": [
                    {
                        "fsid": "category-dir",
                        "name": "目录",
                        "category": 6,
                        "size": 0,
                    },
                    {
                        "fsid": "explicit-file",
                        "name": "显式文件",
                        "isdir": False,
                        "category": 6,
                        "size": 0,
                    },
                    {
                        "fsid": "explicit-dir",
                        "name": "显式目录",
                        "isdir": True,
                        "category": 1,
                        "size": 42,
                    },
                ]
            },
            "/",
        )

        self.assertEqual(
            {entry["fsid"]: entry["isdir"] for entry in entries},
            {
                "category-dir": True,
                "explicit-file": False,
                "explicit-dir": True,
            },
        )

    def test_default_bridge_is_bundled_and_needs_no_command_override(self):
        env = os.environ.copy()
        env.pop("PANLIB_MCP_COMMAND", None)
        env.pop("PANLIB_MCP_BRIDGE", None)
        with mock.patch.dict(os.environ, env, clear=True):
            bridge = MCPBridge.from_environment()
        self.assertEqual(Path(bridge.command[-1]).name, "panlib-mcp-bridge")
        self.assertTrue(Path(bridge.command[-1]).is_file())

    def test_nonzero_bridge_json_error_preserves_structured_code(self):
        bridge_script = self.root / "structured-error.py"
        _executable(
            bridge_script,
            "#!/usr/bin/env python3\n"
            "import json\n"
            "print(json.dumps({'error': {'code': 'INTERNAL', 'message': 'MCP Python SDK is not installed'}}))\n"
            "raise SystemExit(1)\n",
        )
        bridge = MCPBridge((sys.executable, str(bridge_script)))
        with self.assertRaises(MCPBridgeError) as raised:
            bridge.call("file_list", {"dir": "/"})
        self.assertEqual(getattr(raised.exception, "code", None), "INTERNAL")

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PANLIB_MCP_COMMAND": shlex.join([sys.executable, str(self.bridge)]),
                "PANLIB_BRIDGE_STATE": str(self.state),
                "PANLIB_BRIDGE_CALLS": str(self.calls),
                "PANLIB_KEYCHAIN_SECURITY": str(self.security),
                "PANLIB_KEYCHAIN_SERVICE": "com.example.test",
                "PANLIB_KEYCHAIN_ACCOUNT": "mcp",
            }
        )
        return env

    def run_cli(self, args: list[str]) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        proc = subprocess.run(
            [sys.executable, str(LIBRARY)] + args,
            cwd=REPO_ROOT,
            env=self.env(),
            text=True,
            capture_output=True,
        )
        calls = json.loads(self.calls.read_text(encoding="utf-8"))
        return proc, calls

    def test_auth_status_reports_macos_keychain_without_echoing_token(self):
        proc, calls = self.run_cli(["auth-status"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["data"]["backend"], "macos-keychain")
        self.assertTrue(payload["data"]["configured"])
        self.assertNotIn("secret-token", proc.stdout + proc.stderr)
        self.assertEqual(calls, [])

    def test_list_search_and_meta_are_read_only_mcp_calls(self):
        for args, tool in (
            (["list", "--path", "/"], "file_list"),
            (["search", "--keyword", "云中漫步"], "file_keyword_search"),
            (["meta", "--fsid", "src-1"], "file_meta"),
        ):
            with self.subTest(tool=tool):
                proc, calls = self.run_cli(args)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(calls[-1]["tool"], tool)
                self.assertNotIn("secret-token", proc.stdout + proc.stderr)

    def test_search_uses_official_directory_and_pagination_arguments(self):
        proc, calls = self.run_cli(["search", "--path", "/我的资源/Movies", "--keyword", "云中漫步"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls[-1]["tool"], "file_keyword_search")
        self.assertEqual(
            calls[-1]["arguments"],
            {"dir": "/我的资源/Movies", "key": "云中漫步", "page": 1, "num": 100},
        )

    def test_archive_is_plan_first_and_binds_execute_to_plan_ref(self):
        base = [
            "archive",
            "--source",
            "/apps/bdpan/片库/Movies/旧资源",
            "--archive-dir",
            "/我的资源/_已归档_待删除",
            "--new-name",
            "旧资源_旧版_待删除",
            "--ondup",
            "fail",
            "--async",
            "0",
        ]
        plan_proc, plan_calls = self.run_cli(base)
        self.assertEqual(plan_proc.returncode, 0, plan_proc.stderr)
        plan = json.loads(plan_proc.stdout)["data"]
        self.assertEqual(plan["mode"], "plan-only")
        self.assertTrue(plan["execute_required"])
        self.assertRegex(plan["plan_ref"], r"^[0-9a-f]{64}$")
        self.assertNotIn("file_move", [item["tool"] for item in plan_calls])

        execute_proc, execute_calls = self.run_cli(
            base + ["--execute", "--plan-ref", plan["plan_ref"]]
        )
        self.assertEqual(execute_proc.returncode, 0, execute_proc.stderr)
        result = json.loads(execute_proc.stdout)["data"]
        self.assertEqual(result["postcondition"]["status"], "verified")
        self.assertIn("file_move", [item["tool"] for item in execute_calls])
        self.assertNotIn("file_delete", [item["tool"] for item in execute_calls])
        self.assertNotIn("delete", [item["tool"] for item in execute_calls])

    def test_archive_rejects_path_traversal_before_bridge_call(self):
        proc, calls = self.run_cli(
            [
                "archive",
                "--source",
                "/apps/bdpan/片库/Movies/../旧资源",
                "--archive-dir",
                "/我的资源/_已归档_待删除",
            ]
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])

    def test_archive_conflict_fails_without_move(self):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["archive_items"].append({"fsid": "other", "name": "旧资源_旧版_待删除", "isdir": True})
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        proc, calls = self.run_cli(
            [
                "archive",
                "--source",
                "/apps/bdpan/片库/Movies/旧资源",
                "--archive-dir",
                "/我的资源/_已归档_待删除",
                "--new-name",
                "旧资源_旧版_待删除",
            ]
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("file_move", [item["tool"] for item in calls])

    def test_archive_source_search_finds_entry_beyond_parent_first_page(self):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        source = dict(state["source_items"][0])
        state["source_items"] = []
        state["search_items"] = [source]
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

        proc, calls = self.run_cli(
            [
                "archive",
                "--source",
                source["path"],
                "--archive-dir",
                "/我的资源/_已归档_待删除",
                "--new-name",
                "旧资源_搜索归档",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        search_calls = [item for item in calls if item["tool"] == "file_keyword_search"]
        self.assertTrue(search_calls)
        self.assertEqual(
            search_calls[0]["arguments"],
            {
                "dir": "/apps/bdpan/片库/Movies",
                "key": "旧资源",
                "page": 1,
                "num": 100,
            },
        )

    def test_archive_target_search_detects_conflict_beyond_archive_first_page(self):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["search_items"] = [
            {
                "fsid": "searched-conflict",
                "name": "旧资源_旧版_待删除",
                "path": "/我的资源/_已归档_待删除/旧资源_旧版_待删除",
                "isdir": True,
            }
        ]
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

        proc, calls = self.run_cli(
            [
                "archive",
                "--source",
                "/apps/bdpan/片库/Movies/旧资源",
                "--archive-dir",
                "/我的资源/_已归档_待删除",
                "--new-name",
                "旧资源_旧版_待删除",
            ]
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("file_move", [item["tool"] for item in calls])


if __name__ == "__main__":
    unittest.main()
