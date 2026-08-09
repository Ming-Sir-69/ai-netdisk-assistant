"""Official MCP Python SDK bridge for the Baidu Netdisk legacy SSE server.

The SDK owns the SSE session lifecycle and JSON-RPC details.  This wrapper
keeps the access token in memory while constructing the authenticated URL and
turns ``CallToolResult`` into the JSON payload consumed by ``mcp_client``.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:  # scripts import modules as top-level; tests import the panlib package
    from common import redact_text
except ModuleNotFoundError:  # pragma: no cover - exercised by package import
    from .common import redact_text


class BaiduMCPError(RuntimeError):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


def _with_token(url: str, token: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["access_token"] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _load_sdk():
    try:
        from mcp import ClientSession
        from mcp.client.sse import sse_client
    except ImportError as exc:  # pragma: no cover - exercised in missing-deps doctor runs
        raise BaiduMCPError("INTERNAL", "MCP Python SDK is not installed") from exc
    return ClientSession, sse_client


def _block_text(block: Any) -> str | None:
    if isinstance(block, dict):
        value = block.get("text")
        return value if isinstance(value, str) else None
    value = getattr(block, "text", None)
    return value if isinstance(value, str) else None


def _result_payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for block in content:
            text = _block_text(block)
            if text is None:
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        return {"content": content}
    if isinstance(result, dict):
        return result
    return {"result": str(result)}


def _result_error(result: Any) -> str:
    content = getattr(result, "content", None)
    if isinstance(content, list):
        text = " ".join(item for item in (_block_text(block) for block in content) if item)
        if text:
            return text
    return "official MCP tool reported an error"


@dataclass(slots=True)
class BaiduMCPClient:
    url: str = "https://mcp-pan.baidu.com/sse"
    token: str = ""
    timeout: float = 60.0

    @classmethod
    def from_environment(cls, token: str) -> "BaiduMCPClient":
        try:
            timeout = float(os.environ.get("PANLIB_MCP_TIMEOUT", "60"))
        except ValueError as exc:
            raise ValueError("PANLIB_MCP_TIMEOUT must be positive") from exc
        if timeout <= 0:
            raise ValueError("PANLIB_MCP_TIMEOUT must be positive")
        return cls(
            url=os.environ.get("PANLIB_MCP_URL", "https://mcp-pan.baidu.com/sse"),
            token=token,
            timeout=timeout,
        )

    async def _call_tool_async(self, name: str, arguments: dict[str, Any]) -> Any:
        ClientSession, sse_client = _load_sdk()
        stream_url = _with_token(self.url, self.token)
        try:
            # The SDK's sse_client handles endpoint discovery, message POSTs,
            # session initialization and stream shutdown for the legacy server.
            async with sse_client(stream_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
        except BaiduMCPError:
            raise
        except Exception as exc:
            # Do not forward SDK exception text: HTTP errors can contain the
            # authenticated URL.  The cause remains available through the
            # process exit status while stdout/stderr stay credential-safe.
            raise BaiduMCPError("NETWORK", "official MCP session failed") from exc
        if bool(getattr(result, "isError", False)):
            message = redact_text(_result_error(result))
            lowered = message.lower()
            if any(marker in lowered for marker in ("auth", "token", "认证", "登录")):
                code = "AUTH"
            elif any(
                marker in lowered
                for marker in (
                    "params error",
                    "parameter error",
                    "invalid param",
                    "invalid argument",
                    "errno=2",
                    "errno 2",
                    "参数",
                    "格式",
                )
            ):
                code = "INVALID_ARG"
            elif any(marker in lowered for marker in ("parse", "json")):
                code = "PARSE"
            else:
                code = "NETWORK"
            raise BaiduMCPError(code, message)
        return _result_payload(result)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self.token:
            raise BaiduMCPError("AUTH", "MCP access token is missing")
        try:
            return asyncio.run(self._call_tool_async(name, arguments))
        except BaiduMCPError:
            raise
        except RuntimeError as exc:
            # ``asyncio.run`` can fail when called from an already-running
            # loop; the CLI is synchronous, so report a bounded integration
            # error rather than leaking SDK internals.
            raise BaiduMCPError("NETWORK", "MCP session could not start") from exc
