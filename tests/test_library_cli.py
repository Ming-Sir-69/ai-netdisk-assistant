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
    if directory == "/我的资源/Movies":
        print(json.dumps({"list": state.get("my_source_items", [])}, ensure_ascii=False))
    elif directory.startswith("/我的资源/Movies/"):
        print(json.dumps({"list": state.get("my_dirs", {}).get(directory, [])}, ensure_ascii=False))
    elif directory == "/apps/bdpan/片库/Movies":
        print(json.dumps({"list": state.get("apps_items", state["source_items"])}, ensure_ascii=False))
    elif directory.startswith("/apps/bdpan/片库/Movies/"):
        items = state.get("apps_dirs", {}).get(directory, [])
        if state.pop("inject_target_child_once", False):
            items = list(items) + [
                {
                    "fsid": "injected-target-child",
                    "name": "外部并发文件.mkv",
                    "path": directory + "/外部并发文件.mkv",
                    "isdir": False,
                    "size": 1,
                }
            ]
            state.setdefault("apps_dirs", {})[directory] = items
            open(state_path, "w", encoding="utf-8").write(json.dumps(state, ensure_ascii=False))
        print(json.dumps({"list": items}, ensure_ascii=False))
    elif directory in (
        "/我的资源/_已归档_待删除",
        "/apps/bdpan/片库/_已归档_待删除",
    ):
        archive_page = [] if state.get("archive_list_hidden") else state["archive_items"]
        print(json.dumps({"list": archive_page}, ensure_ascii=False))
    elif directory == "/":
        print(json.dumps({"list": [{"fsid": "root-1", "name": "我的资源", "isdir": True}]}, ensure_ascii=False))
    else:
        print(json.dumps({"list": []}, ensure_ascii=False))
elif tool == "file_keyword_search":
    if args.get("key") in {"旧资源", "旧资源_旧版_待删除"}:
        matches = [
            item for item in state.get("search_items", [])
            if item.get("name") == args.get("key")
        ]
        print(json.dumps({"list": matches}, ensure_ascii=False))
    else:
        print(json.dumps({"list": [{"fsid": "search-1", "name": "云中漫步", "path": "/我的资源/Movies/云中漫步"}]}, ensure_ascii=False))
elif tool == "file_meta":
    fsids = args.get("fsids")
    if not isinstance(fsids, list) or not fsids:
        print(json.dumps({"error": {"code": "INVALID_ARG", "message": "Invalid parameter: fsids is required"}}, ensure_ascii=False))
        raise SystemExit(0)
    print(json.dumps({"data": {"list": [{"fsid": fsids[0], "filename": "旧资源", "isdir": True, "size": 123}]}}, ensure_ascii=False))
elif tool == "file_move":
    if not isinstance(args.get("filelist"), str):
        print(json.dumps({"error": {"code": "INVALID_ARG", "message": "filelist must be JSON string"}}))
        raise SystemExit(0)
    if state.pop("fail_move_once", False):
        open(state_path, "w", encoding="utf-8").write(json.dumps(state, ensure_ascii=False))
        print(json.dumps({"error": {"code": "NETWORK", "message": "simulated file_move failure"}}))
        raise SystemExit(0)
    move = json.loads(args["filelist"])[0]
    if move["path"].startswith("/我的资源/Movies/"):
        source_parent = move["path"].rsplit("/", 1)[0]
        if source_parent == "/我的资源/Movies":
            source_items = state.setdefault("my_source_items", [])
        else:
            source_items = state.setdefault("my_dirs", {}).setdefault(source_parent, [])
    else:
        source_items = state["source_items"]
    source = next(item for item in source_items if item["path"] == move["path"])
    source_items.remove(source)
    state["search_items"] = [
        item for item in state.get("search_items", [])
        if item.get("path") != move["path"]
    ]
    moved = dict(source)
    moved["path"] = move["dest"].rstrip("/") + "/" + move["newname"]
    moved["name"] = move["newname"]
    if move["dest"].startswith("/apps/bdpan/片库/Movies/"):
        state.setdefault("apps_dirs", {}).setdefault(move["dest"], []).append(moved)
    elif move["dest"] == "/apps/bdpan/片库/Movies":
        state.setdefault("apps_items", []).append(moved)
    else:
        state["archive_items"].append(moved)
    state["search_items"].append(moved)
    open(state_path, "w", encoding="utf-8").write(json.dumps(state, ensure_ascii=False))
    print(json.dumps({"ok": True}))
elif tool == "make_dir":
    path = args["path"]
    apps_items = state.setdefault("apps_items", list(state.get("source_items", [])))
    if not any(item.get("path") == path for item in apps_items):
        apps_items.append({
            "fsid": "target-dir-1",
            "name": path.rsplit("/", 1)[-1],
            "path": path,
            "isdir": True,
            "size": 0,
        })
    state.setdefault("apps_dirs", {})[path] = []
    open(state_path, "w", encoding="utf-8").write(json.dumps(state, ensure_ascii=False))
    print(json.dumps({"ok": True, "path": path}))
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
                    "my_source_items": [],
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

    def test_meta_sends_plural_fsids_array_like_the_official_api(self):
        # 2026-08-15 实测：百度 file_meta 只接受复数数组 ``fsids``；单数 ``fsid``
        # 一律被拒为 "Invalid parameter: fsids is required"（errno 1002）。
        proc, calls = self.run_cli(["meta", "--fsid", "src-1"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls[-1]["tool"], "file_meta")
        self.assertEqual(calls[-1]["arguments"], {"fsids": ["src-1"]})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["data"]["meta"]["fsid"], "src-1")
        self.assertEqual(payload["data"]["meta"]["filename"], "旧资源")

    def test_meta_by_path_resolves_a_unique_fsid_before_calling_file_meta(self):
        proc, calls = self.run_cli(["meta", "--path", "/apps/bdpan/片库/Movies/旧资源"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls[-2]["tool"], "file_list")
        self.assertEqual(calls[-1]["tool"], "file_meta")
        self.assertEqual(calls[-1]["arguments"], {"fsids": ["src-1"]})

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
            "/apps/bdpan/片库/_已归档_待删除",
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

    def test_archive_without_destination_derives_the_apps_archive_root(self):
        proc, calls = self.run_cli(
            [
                "archive",
                "--source",
                "/apps/bdpan/片库/Movies/旧资源",
                "--new-name",
                "旧资源_旧版_待删除",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)["data"]
        self.assertEqual(payload["archive_dir"], "/apps/bdpan/片库/_已归档_待删除")
        self.assertNotIn("file_move", [item["tool"] for item in calls])

    def test_archive_rejects_a_cross_root_destination(self):
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

    def test_archive_rejects_path_traversal_before_bridge_call(self):
        proc, calls = self.run_cli(
            [
                "archive",
                "--source",
                "/apps/bdpan/片库/Movies/../旧资源",
                "--archive-dir",
                "/apps/bdpan/片库/_已归档_待删除",
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
                "/apps/bdpan/片库/_已归档_待删除",
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
                "/apps/bdpan/片库/_已归档_待删除",
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
                "path": "/apps/bdpan/片库/_已归档_待删除/旧资源_旧版_待删除",
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
                "/apps/bdpan/片库/_已归档_待删除",
                "--new-name",
                "旧资源_旧版_待删除",
            ]
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("file_move", [item["tool"] for item in calls])

    def test_archive_execute_verifies_source_and_target_beyond_first_page(self):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["archive_list_hidden"] = True
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        base = [
            "archive",
            "--source",
            "/apps/bdpan/片库/Movies/旧资源",
            "--new-name",
            "旧资源_旧版_待删除",
        ]

        plan_proc, _ = self.run_cli(base)
        self.assertEqual(plan_proc.returncode, 0, plan_proc.stderr)
        plan_ref = json.loads(plan_proc.stdout)["data"]["plan_ref"]
        execute_proc, calls = self.run_cli(base + ["--execute", "--plan-ref", plan_ref])

        self.assertEqual(execute_proc.returncode, 0, execute_proc.stderr)
        result = json.loads(execute_proc.stdout)["data"]
        self.assertEqual(result["postcondition"]["status"], "verified")
        search_keys = [
            item["arguments"].get("key")
            for item in calls
            if item["tool"] == "file_keyword_search"
        ]
        self.assertIn("旧资源", search_keys)
        self.assertIn("旧资源_旧版_待删除", search_keys)

    def test_migrate_is_plan_first_and_moves_my_resource_media_into_apps_container(self):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["my_source_items"] = [
            {
                "fsid": "my-movie-1",
                "name": "旧片名.mkv",
                "path": "/我的资源/Movies/旧片名.mkv",
                "isdir": False,
                "size": 456,
            }
        ]
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        base = [
            "migrate",
            "--source",
            "/我的资源/Movies/旧片名.mkv",
            "--target-dir",
            "/apps/bdpan/片库/Movies/规范片名.2020.tt1234567",
            "--new-name",
            "规范片名.2020.1080p.mkv",
        ]

        plan_proc, plan_calls = self.run_cli(base)
        self.assertEqual(plan_proc.returncode, 0, plan_proc.stderr)
        plan = json.loads(plan_proc.stdout)["data"]
        self.assertEqual(plan["mode"], "plan-only")
        self.assertTrue(plan["execute_required"])
        self.assertRegex(plan["plan_ref"], r"^[0-9a-f]{64}$")
        self.assertEqual(plan["source"], "/我的资源/Movies/旧片名.mkv")
        self.assertEqual(plan["target_dir"], "/apps/bdpan/片库/Movies/规范片名.2020.tt1234567")
        self.assertEqual(
            plan["target"],
            "/apps/bdpan/片库/Movies/规范片名.2020.tt1234567/规范片名.2020.1080p.mkv",
        )
        self.assertEqual(plan["actions"][1]["dest"], "/apps/bdpan/片库/Movies/规范片名.2020.tt1234567")
        self.assertEqual(plan["actions"][1]["newname"], "规范片名.2020.1080p.mkv")
        self.assertNotIn("file_move", [item["tool"] for item in plan_calls])

        execute_proc, execute_calls = self.run_cli(
            base + ["--execute", "--plan-ref", plan["plan_ref"]]
        )
        self.assertEqual(execute_proc.returncode, 0, execute_proc.stderr)
        result = json.loads(execute_proc.stdout)["data"]
        self.assertEqual(result["postcondition"]["status"], "verified")
        self.assertTrue(result["postcondition"]["source_absent"])
        self.assertTrue(result["postcondition"]["target_present"])
        tools = [item["tool"] for item in execute_calls]
        self.assertIn("make_dir", tools)
        moves = [item for item in execute_calls if item["tool"] == "file_move"]
        self.assertEqual(len(moves), 1)
        self.assertLess(tools.index("make_dir"), tools.index("file_move"))
        make_dir_calls = [item for item in execute_calls if item["tool"] == "make_dir"]
        self.assertEqual(
            make_dir_calls[0]["arguments"],
            {
                "path": "/apps/bdpan/片库/Movies/规范片名.2020.tt1234567",
                "rtype": 0,
            },
        )
        move_index = tools.index("file_move")
        self.assertIn(tools[move_index - 1], {"file_list", "file_keyword_search"})
        self.assertEqual(tools[move_index + 1], "file_list")
        self.assertEqual(moves[0]["arguments"]["async"], 0)
        self.assertEqual(moves[0]["arguments"]["ondup"], "fail")
        self.assertNotIn("file_delete", [item["tool"] for item in execute_calls])
        self.assertNotIn("delete", [item["tool"] for item in execute_calls])

    def test_migrate_accepts_an_exact_media_file_but_rejects_directories_and_arbitrary_roots(self):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["my_source_items"] = [
            {
                "fsid": "my-file-1",
                "name": "影片.mkv",
                "path": "/我的资源/Movies/影片.mkv",
                "isdir": False,
                "size": 123,
            }
        ]
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        proc, calls = self.run_cli(
            [
                "migrate",
                "--source",
                "/我的资源/Movies/影片.mkv",
                "--target-dir",
                "/apps/bdpan/片库/Movies/影片.2020.tt1234567",
            ]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["data"]["source_item"]["isdir"], False)
        self.assertNotIn("file_move", [item["tool"] for item in calls])

        nested_state = json.loads(self.state.read_text(encoding="utf-8"))
        nested_state["my_source_items"] = []
        nested_state["my_dirs"] = {
            "/我的资源/Movies/卓别林": [
                {
                    "fsid": "nested-file-1",
                    "name": "摩登时代.mkv",
                    "path": "/我的资源/Movies/卓别林/摩登时代.mkv",
                    "isdir": False,
                    "size": 321,
                }
            ]
        }
        self.state.write_text(json.dumps(nested_state, ensure_ascii=False), encoding="utf-8")
        nested_proc, nested_calls = self.run_cli(
            [
                "migrate",
                "--source",
                "/我的资源/Movies/卓别林/摩登时代.mkv",
                "--target-dir",
                "/apps/bdpan/片库/Movies/Modern.Times.1936.tt0021749",
            ]
        )
        self.assertEqual(nested_proc.returncode, 0, nested_proc.stderr)
        self.assertEqual(
            json.loads(nested_proc.stdout)["data"]["source"],
            "/我的资源/Movies/卓别林/摩登时代.mkv",
        )
        self.assertNotIn("file_move", [item["tool"] for item in nested_calls])

        for source, target_dir in (
            (
                "/我的资源/Movies/影片目录",
                "/apps/bdpan/片库/Movies/影片.2020.tt1234567",
            ),
            (
                "/apps/bdpan/片库/Movies/影片.mkv",
                "/apps/bdpan/片库/Movies/影片.2020.tt1234567",
            ),
            (
                "/我的资源/Movies/影片.mkv",
                "/我的资源/Movies/影片.2020.tt1234567",
            ),
        ):
            with self.subTest(source=source, target_dir=target_dir):
                state = json.loads(self.state.read_text(encoding="utf-8"))
                state["my_source_items"] = [
                    {
                        "fsid": "my-dir-1",
                        "name": "影片目录",
                        "path": "/我的资源/Movies/影片目录",
                        "isdir": True,
                        "size": 0,
                    }
                ]
                self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                rejected, rejected_calls = self.run_cli(
                    ["migrate", "--source", source, "--target-dir", target_dir]
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(json.loads(rejected.stdout)["error"]["code"], "INVALID_ARG")
                self.assertNotIn("file_move", [item["tool"] for item in rejected_calls])

    def test_migrate_reuses_existing_target_for_subtitle_and_rejects_same_name(self):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        target_dir = "/apps/bdpan/片库/Movies/中国机长.2019.tt9586297"
        existing_video = {
            "fsid": "target-video-1",
            "name": "中国机长.2019.1080p.mkv",
            "path": target_dir + "/中国机长.2019.1080p.mkv",
            "isdir": False,
            "size": 999,
        }
        state["my_source_items"] = [
            {
                "fsid": "my-subtitle-1",
                "name": "中国机长.srt",
                "path": "/我的资源/Movies/中国机长.srt",
                "isdir": False,
                "size": 12,
            }
        ]
        state["apps_items"] = [
            {
                "fsid": "target-dir-1",
                "name": "中国机长.2019.tt9586297",
                "path": target_dir,
                "isdir": True,
                "size": 0,
            }
        ]
        state["apps_dirs"] = {target_dir: [existing_video]}
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

        base = [
            "migrate",
            "--source",
            "/我的资源/Movies/中国机长.srt",
            "--target-dir",
            target_dir,
            "--new-name",
            "中国机长.2019.zh-Hans.srt",
        ]
        plan_proc, plan_calls = self.run_cli(base)
        self.assertEqual(plan_proc.returncode, 0, plan_proc.stderr)
        plan = json.loads(plan_proc.stdout)["data"]
        self.assertTrue(plan["target_exists"])
        self.assertEqual([action["action"] for action in plan["actions"]], ["file_move"])
        self.assertNotIn("make_dir", [item["tool"] for item in plan_calls])

        execute_proc, execute_calls = self.run_cli(
            base + ["--execute", "--plan-ref", plan["plan_ref"]]
        )
        self.assertEqual(execute_proc.returncode, 0, execute_proc.stderr)
        self.assertNotIn("make_dir", [item["tool"] for item in execute_calls])
        self.assertEqual(
            len([item for item in execute_calls if item["tool"] == "file_move"]),
            1,
        )

        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["my_source_items"] = [
            {
                "fsid": "my-subtitle-2",
                "name": "中国机长.srt",
                "path": "/我的资源/Movies/中国机长.srt",
                "isdir": False,
                "size": 12,
            }
        ]
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self.calls.write_text("[]", encoding="utf-8")
        conflict_proc, conflict_calls = self.run_cli(
            base[:-1] + ["中国机长.2019.1080p.mkv"]
        )
        self.assertNotEqual(conflict_proc.returncode, 0)
        self.assertEqual(json.loads(conflict_proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("file_move", [item["tool"] for item in conflict_calls])

    def test_migrate_stops_on_target_change_between_make_dir_and_file_move(self):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["my_source_items"] = [
            {
                "fsid": "toctou-source",
                "name": "待迁移.mkv",
                "path": "/我的资源/Movies/待迁移.mkv",
                "isdir": False,
                "size": 17,
            }
        ]
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        base = [
            "migrate",
            "--source",
            "/我的资源/Movies/待迁移.mkv",
            "--target-dir",
            "/apps/bdpan/片库/Movies/TOCTOU.2020.tt1234567",
        ]
        plan_proc, _ = self.run_cli(base)
        self.assertEqual(plan_proc.returncode, 0, plan_proc.stderr)
        plan = json.loads(plan_proc.stdout)["data"]

        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["inject_target_child_once"] = True
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self.calls.write_text("[]", encoding="utf-8")
        execute_proc, calls = self.run_cli(base + ["--execute", "--plan-ref", plan["plan_ref"]])

        self.assertNotEqual(execute_proc.returncode, 0)
        self.assertEqual(json.loads(execute_proc.stdout)["error"]["code"], "INVALID_ARG")
        tools = [item["tool"] for item in calls]
        self.assertIn("make_dir", tools)
        self.assertNotIn("file_move", tools)
        persisted = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(
            len(persisted["apps_dirs"]["/apps/bdpan/片库/Movies/TOCTOU.2020.tt1234567"]),
            1,
        )

    def test_migrate_preserves_empty_target_after_file_move_failure_without_retry(self):
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["my_source_items"] = [
            {
                "fsid": "partial-source",
                "name": "部分失败.mkv",
                "path": "/我的资源/Movies/部分失败.mkv",
                "isdir": False,
                "size": 19,
            }
        ]
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        base = [
            "migrate",
            "--source",
            "/我的资源/Movies/部分失败.mkv",
            "--target-dir",
            "/apps/bdpan/片库/Movies/Partial.2020.tt1234567",
        ]
        plan_proc, _ = self.run_cli(base)
        self.assertEqual(plan_proc.returncode, 0, plan_proc.stderr)
        plan = json.loads(plan_proc.stdout)["data"]

        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["fail_move_once"] = True
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self.calls.write_text("[]", encoding="utf-8")
        execute_proc, calls = self.run_cli(base + ["--execute", "--plan-ref", plan["plan_ref"]])

        self.assertNotEqual(execute_proc.returncode, 0)
        self.assertEqual(json.loads(execute_proc.stdout)["error"]["code"], "NETWORK")
        tools = [item["tool"] for item in calls]
        self.assertEqual(tools.count("make_dir"), 1)
        self.assertEqual(tools.count("file_move"), 1)
        persisted = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["apps_dirs"]["/apps/bdpan/片库/Movies/Partial.2020.tt1234567"],
            [],
        )
        self.assertEqual(len(persisted["my_source_items"]), 1)


if __name__ == "__main__":
    unittest.main()
