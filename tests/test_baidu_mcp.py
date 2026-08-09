from __future__ import annotations

import json
import sys
import types
import unittest
from contextlib import asynccontextmanager
from unittest import mock

from panlib.baidu_mcp import BaiduMCPClient, BaiduMCPError


class _Text:
    def __init__(self, text: str):
        self.text = text


class _Result:
    def __init__(self, *, value=None, error: bool = False):
        self.isError = error
        self.structuredContent = value
        self.content = [_Text(json.dumps(value, ensure_ascii=False))] if value is not None else []


class BaiduMCPClientTests(unittest.TestCase):
    def _fake_sdk(self, calls: list[tuple[str, object]], result: _Result):
        @asynccontextmanager
        async def fake_sse(url):
            calls.append(("sse", url))
            yield object(), object()

        class FakeSession:
            def __init__(self, read, write):
                calls.append(("session", (read, write)))

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def initialize(self):
                calls.append(("initialize", None))

            async def call_tool(self, name, arguments):
                calls.append(("call_tool", (name, arguments)))
                return result

        fake_mcp = types.ModuleType("mcp")
        fake_mcp.ClientSession = FakeSession
        fake_client = types.ModuleType("mcp.client")
        fake_sse_module = types.ModuleType("mcp.client.sse")
        fake_sse_module.sse_client = fake_sse
        return {
            "mcp": fake_mcp,
            "mcp.client": fake_client,
            "mcp.client.sse": fake_sse_module,
        }

    def test_official_sdk_session_initializes_calls_tool_and_keeps_token_only_in_url(self):
        calls: list[tuple[str, object]] = []
        fake_modules = self._fake_sdk(calls, _Result(value={"list": []}))
        with mock.patch.dict(sys.modules, fake_modules):
            result = BaiduMCPClient(
                url="https://mcp-pan.baidu.test/sse",
                token="secret-token",
            ).call_tool("file_list", {"dir": "/"})
        self.assertEqual(result, {"list": []})
        self.assertEqual([item[0] for item in calls], ["sse", "session", "initialize", "call_tool"])
        self.assertIn("access_token=secret-token", calls[0][1])
        self.assertEqual(calls[-1][1], ("file_list", {"dir": "/"}))

    def test_official_sdk_is_error_is_not_reported_as_success(self):
        calls: list[tuple[str, object]] = []
        fake_modules = self._fake_sdk(calls, _Result(error=True))
        with mock.patch.dict(sys.modules, fake_modules):
            with self.assertRaises(BaiduMCPError) as raised:
                BaiduMCPClient(
                    url="https://mcp-pan.baidu.test/sse",
                    token="secret-token",
                ).call_tool("file_move", {"async": 0, "ondup": "fail", "filelist": []})
        self.assertEqual(raised.exception.code, "NETWORK")
        self.assertNotIn("secret-token", str(raised.exception))

    def test_official_sdk_parameter_error_is_invalid_arg_not_network(self):
        calls: list[tuple[str, object]] = []
        result = _Result(error=True)
        result.content = [_Text("params error errno=2")]
        fake_modules = self._fake_sdk(calls, result)
        with mock.patch.dict(sys.modules, fake_modules):
            with self.assertRaises(BaiduMCPError) as raised:
                BaiduMCPClient(
                    url="https://mcp-pan.baidu.test/sse",
                    token="secret-token",
                ).call_tool("file_move", {"async": 0, "ondup": "fail"})
        self.assertEqual(raised.exception.code, "INVALID_ARG")
        self.assertNotIn("secret-token", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
