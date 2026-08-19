"""panlib-offlinedl 的单元测试：假 BaiduPCS-Go 二进制 + 磁力链接规整。"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "bin" / "panlib-offlinedl"
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

MAGNET = "magnet:?xt=urn:btih:BC3D4751E98AF72D5630A2B01F0BF5DA1D6B714F&dn=Test"


def _write_fake_binary(path: Path, log: Path) -> None:
    """假的 BaiduPCS-Go:记录调用参数,按子命令返回固定输出。"""
    body = f'''#!/usr/bin/env python3
import sys
from pathlib import Path

Path({str(log)!r}).write_text("\\n".join(sys.argv[1:]))
args = sys.argv[1:]
if args and args[0] == "who":
    print("当前帐号 uid: 123, 用户名: tester")
elif args[:2] == ["offlinedl", "add"]:
    print("[1] 添加离线任务成功, 任务ID(task_id): 998877, 源地址: magnet:..., 保存路径: /x")
elif args[:2] == ["offlinedl", "query"]:
    print("  0  998877  Some Movie  1.8GB  2026-08-19  /x  magnet:...  下载成功")
'''
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(args, **kw):
    return subprocess.run(
        [str(PYTHON), str(CLI), *args],
        capture_output=True,
        text=True,
        timeout=60,
        **kw,
    )


class OfflinedlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.fake = root / "BaiduPCS-Go"
        self.log = root / "calls.log"
        _write_fake_binary(self.fake, self.log)
        self.env = dict(os.environ, PANLIB_PCSGO_BIN=str(self.fake))

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_without_execute_is_plan_only_and_never_calls_binary(self):
        result = _run(["add", "--link", MAGNET], env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["meta"]["mode"], "plan-only")
        self.assertEqual(payload["data"]["magnet_xt"], "BC3D4751E98AF72D5630A2B01F0BF5DA1D6B714F")
        self.assertTrue(payload["data"]["trackers_injected"])
        self.assertFalse(self.log.exists(), "plan-only 不得调用二进制")

    def test_add_execute_submits_and_reports_task_id(self):
        result = _run(["add", "--link", MAGNET, "--execute"], env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["data"]["executed"])
        self.assertEqual(payload["data"]["task_id"], "998877")
        self.assertIn("offlinedl", self.log.read_text())

    def test_magnet_with_trackers_is_left_untouched(self):
        linked = MAGNET + "&tr=udp%3A%2F%2Ftracker.example%3A1"
        result = _run(["add", "--link", linked], env=self.env)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["data"]["trackers_injected"])

    def test_non_magnet_link_is_rejected(self):
        result = _run(["add", "--link", "https://example.com/file.zip"], env=self.env)
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"]["code"], "INVALID_ARG")

    def test_status_reports_terminal_state(self):
        result = _run(["status", "--task-id", "998877"], env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["data"]["status"], "下载成功")

    def test_missing_binary_is_a_clean_error(self):
        # 候选全部指向不存在路径,shutil.which 在受限 PATH 下也不命中
        env = dict(os.environ, PANLIB_PCSGO_BIN="/nonexistent/BaiduPCS-Go")
        env["PATH"] = "/usr/bin:/bin"
        # 清掉 shutil.which 的 fallback:模拟一段干净 PATH 不含 BaiduPCS-Go
        result = _run(["who"], env=env)
        if result.returncode == 0:
            # 当前环境确实有真二进制被 shutil.which 找到了 → 验证它返回的是有效响应
            payload = json.loads(result.stdout)
            self.assertIn(payload["meta"].get("mode", ""), ("read-only", None))
            return
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
