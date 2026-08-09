"""A narrow JSON bridge for the official Baidu Netdisk MCP tools.

The host MCP client owns OAuth and talks to the official service.  This local
adapter only sends tool names and structured arguments to a user-configured
bridge process; it never receives or prints an access token.  The bridge may
return either the official ``list`` shape or the normalized ``items`` shape,
and this module converts both to a small deterministic inventory used by the
library CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping

try:  # scripts import modules as top-level; tests import the panlib package
    from common import redact_text
except ModuleNotFoundError:  # pragma: no cover - exercised by package import
    from .common import redact_text


class MCPBridgeError(RuntimeError):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


def _classify_error(value: object) -> str:
    text = str(value).lower()
    if any(marker in text for marker in ("auth", "oauth", "token", "登录", "认证")):
        return "AUTH"
    if any(marker in text for marker in ("permission", "scope", "403", "权限")):
        return "PERMISSION"
    if any(marker in text for marker in ("not found", "不存在", "失效")):
        return "NOT_FOUND"
    if any(
        marker in text
        for marker in (
            "invalid",
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
        return "INVALID_ARG"
    if any(marker in text for marker in ("parse", "json")):
        return "PARSE"
    return "NETWORK"


def validate_mcp_path(value: str, *, allow_root: bool = True) -> str:
    """Validate one exact absolute POSIX path for full-drive MCP operations."""

    if not isinstance(value, str) or not value:
        raise ValueError("path must be a non-empty absolute POSIX path")
    if not value.startswith("/"):
        raise ValueError("path must be absolute")
    if "\\" in value or "//" in value:
        raise ValueError("path must use single POSIX separators")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("path contains a control character")
    if value != "/" and value.endswith("/"):
        raise ValueError("path must identify one exact entry")
    path = PurePosixPath(value)
    if not allow_root and value == "/":
        raise ValueError("root path is not an exact archive source")
    if any(part in {".", ".."} for part in path.parts):
        raise ValueError("path traversal is not allowed")
    return value


def parent_path(value: str) -> str:
    path = validate_mcp_path(value)
    return str(PurePosixPath(path).parent)


def basename(value: str) -> str:
    path = validate_mcp_path(value, allow_root=False)
    return PurePosixPath(path).name


def _response_payload(value: Any) -> Any:
    """Unwrap common MCP JSON envelopes without interpreting credentials."""

    if isinstance(value, Mapping) and "structuredContent" in value:
        return _response_payload(value["structuredContent"])
    if isinstance(value, Mapping) and "content" in value:
        content = value.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        try:
                            return _response_payload(json.loads(text))
                        except json.JSONDecodeError:
                            continue
        return value
    return value


def _structured_bridge_error(payload: Any) -> MCPBridgeError | None:
    if not isinstance(payload, Mapping) or not payload.get("error"):
        return None
    error = payload.get("error")
    if isinstance(error, Mapping):
        code = str(error.get("code") or _classify_error(error.get("message", "")))
        message = str(error.get("message") or error.get("msg") or "MCP request failed")
        details = error.get("details")
    else:
        code = _classify_error(error)
        message = str(error)
        details = None
    return MCPBridgeError(code, redact_text(message), details)


@dataclass(slots=True)
class MCPBridge:
    command: tuple[str, ...]
    timeout: int = 60

    @classmethod
    def from_environment(cls) -> "MCPBridge":
        raw = os.environ.get("PANLIB_MCP_COMMAND") or os.environ.get("PANLIB_MCP_BRIDGE")
        if raw:
            try:
                command = tuple(shlex.split(raw))
            except ValueError as exc:
                raise ValueError("PANLIB_MCP_COMMAND is not valid shell syntax") from exc
            if not command:
                raise ValueError("PANLIB_MCP_COMMAND must not be empty")
        else:
            bridge = Path(__file__).resolve().parent.parent / "bin" / "panlib-mcp-bridge"
            command = (sys.executable, str(bridge))
        try:
            timeout = int(os.environ.get("PANLIB_MCP_TIMEOUT", "60"))
        except ValueError as exc:
            raise ValueError("PANLIB_MCP_TIMEOUT must be a positive integer") from exc
        if timeout <= 0:
            raise ValueError("PANLIB_MCP_TIMEOUT must be a positive integer")
        return cls(command, timeout)

    def call(self, tool: str, arguments: Mapping[str, Any] | None = None) -> Any:
        if not tool or any(char.isspace() for char in tool):
            raise ValueError("MCP tool name is invalid")
        request = {"tool": tool, "arguments": dict(arguments or {})}
        try:
            result = subprocess.run(
                list(self.command),
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MCPBridgeError("NETWORK", "MCP bridge timed out") from exc
        except OSError as exc:
            raise MCPBridgeError("AUTH", "MCP bridge is unavailable") from exc
        if result.returncode != 0:
            # The bundled bridge emits a structured JSON error before exiting
            # non-zero.  Preserve its code (AUTH/INTERNAL/INVALID_ARG/PARSE)
            # instead of flattening every process failure to NETWORK.
            try:
                structured = _response_payload(json.loads(result.stdout))
            except (json.JSONDecodeError, TypeError):
                structured = None
            error = _structured_bridge_error(structured)
            if error is not None:
                raise error
            message = redact_text(result.stderr.strip() or result.stdout.strip() or "MCP bridge failed")
            raise MCPBridgeError(_classify_error(message), message)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise MCPBridgeError("PARSE", "MCP bridge returned invalid JSON") from exc
        payload = _response_payload(payload)
        error = _structured_bridge_error(payload)
        if error is not None:
            raise error
        return payload


def normalize_entries(payload: Any, directory: str) -> list[dict[str, Any]]:
    """Normalize official ``list`` or bridge ``items`` entries."""

    payload = _response_payload(payload)
    raw_items: Any
    if isinstance(payload, Mapping):
        raw_items = payload.get("list", payload.get("items", payload.get("data", [])))
    else:
        raw_items = payload
    if isinstance(raw_items, Mapping):
        raw_items = raw_items.get("list", raw_items.get("items", []))
    if not isinstance(raw_items, list):
        raise MCPBridgeError("PARSE", "MCP file_list returned a non-list result")
    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name") or item.get("server_filename") or item.get("filename")
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            continue
        path = item.get("path") or item.get("full_path")
        if not isinstance(path, str) or not path:
            path = "/" + name if directory == "/" else directory.rstrip("/") + "/" + name
        try:
            path = validate_mcp_path(path, allow_root=False)
        except ValueError:
            continue
        fsid = item.get("fsid", item.get("fs_id", item.get("id")))
        # The official file_list payload often omits ``isdir``.  In that
        # shape Baidu marks directories as category=6 with a zero size.  An
        # explicit isdir/is_dir/is_directory value always wins, including a
        # deliberate false value on a category-6 entry.
        isdir_key = next(
            (key for key in ("isdir", "is_dir", "is_directory") if key in item),
            None,
        )
        if isdir_key is not None:
            raw_isdir = item[isdir_key]
            if isinstance(raw_isdir, str):
                isdir = raw_isdir.strip().lower() not in {"", "0", "false", "no", "off"}
            else:
                isdir = bool(raw_isdir)
        else:
            category = item.get("category")
            size = item.get("size")
            isdir = str(category).strip() == "6" and size in (0, "0")
        normalized.append(
            {
                "name": name,
                "path": path,
                "fsid": str(fsid) if fsid is not None else None,
                "isdir": isdir,
                "size": item.get("size"),
            }
        )
    return normalized


def list_directory(client: MCPBridge, directory: str) -> list[dict[str, Any]]:
    path = validate_mcp_path(directory)
    return normalize_entries(client.call("file_list", {"dir": path, "page": 1}), path)


def search_library(
    client: MCPBridge,
    keyword: str,
    directory: str = "/",
) -> list[dict[str, Any]]:
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("keyword must not be empty")
    directory = validate_mcp_path(directory)
    # The official Baidu tool requires all four fields.  ``key`` is the search
    # term; ``dir`` scopes the search and ``num`` keeps the result bounded.
    payload = client.call(
        "file_keyword_search",
        {"dir": directory, "key": keyword.strip(), "page": 1, "num": 100},
    )
    return normalize_entries(payload, directory)


def meta_library(client: MCPBridge, *, path: str | None = None, fsid: str | None = None) -> Any:
    if bool(path) == bool(fsid):
        raise ValueError("provide exactly one of path or fsid")
    arguments = {"path": validate_mcp_path(path, allow_root=False)} if path else {"fsid": str(fsid)}
    payload = _response_payload(client.call("file_meta", arguments))
    if isinstance(payload, Mapping) and payload.get("data") is not None:
        payload = payload["data"]
    if not isinstance(payload, Mapping):
        raise MCPBridgeError("PARSE", "MCP file_meta returned an invalid result")
    return dict(payload)


def _exact_path_matches(
    entries: list[dict[str, Any]], path: str, name: str
) -> list[dict[str, Any]]:
    """Return entries that identify ``name`` directly under its parent."""

    parent = parent_path(path)
    return [
        item
        for item in entries
        if item.get("path") == path
        or (item.get("name") == name and parent_path(str(item.get("path") or "")) == parent)
    ]


def _source_entry(client: MCPBridge, source: str) -> dict[str, Any]:
    source = validate_mcp_path(source, allow_root=False)
    parent = parent_path(source)
    entries = list_directory(client, parent)
    matches = _exact_path_matches(entries, source, basename(source))
    if not matches:
        # file_list is page-bounded; use the official keyword search scoped to
        # the parent when the exact source is outside that first page.
        matches = _exact_path_matches(search_library(client, basename(source), parent), source, basename(source))
    if len(matches) != 1:
        raise MCPBridgeError("NOT_FOUND", "archive source was not found exactly once")
    item = matches[0]
    if not item["isdir"]:
        raise MCPBridgeError("INVALID_ARG", "archive source must be a directory")
    return item


def _archive_snapshot(client: MCPBridge, source: str, archive_dir: str, new_name: str) -> dict[str, Any]:
    source = validate_mcp_path(source, allow_root=False)
    archive_dir = validate_mcp_path(archive_dir, allow_root=False)
    if not isinstance(new_name, str) or not new_name.strip() or "/" in new_name or "\\" in new_name:
        raise ValueError("new-name must be one non-empty filename")
    new_name = new_name.strip()
    if new_name in {".", ".."} or any(ord(char) < 32 or ord(char) == 127 for char in new_name):
        raise ValueError("new-name contains an unsafe character")
    source_item = _source_entry(client, source)
    target_items = list_directory(client, archive_dir)
    target_path = archive_dir.rstrip("/") + "/" + new_name
    target_matches = _exact_path_matches(target_items, target_path, new_name)
    if not target_matches:
        # As with the source, a first-page listing is insufficient to prove a
        # destination name is free.  Search the exact archive directory too.
        target_matches = _exact_path_matches(
            search_library(client, new_name, archive_dir), target_path, new_name
        )
    if target_matches:
        raise MCPBridgeError("INVALID_ARG", "archive destination already exists")
    signature = {
        "source": source_item,
        "archive_dir": archive_dir,
        "new_name": new_name,
        "target_names": sorted(item["name"] for item in target_items),
    }
    plan_ref = hashlib.sha256(
        json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "source": source,
        "archive_dir": archive_dir,
        "new_name": new_name,
        "source_item": source_item,
        "plan_ref": plan_ref,
    }


def build_archive_plan(client: MCPBridge, source: str, archive_dir: str, new_name: str | None) -> dict[str, Any]:
    source = validate_mcp_path(source, allow_root=False)
    effective_name = new_name.strip() if isinstance(new_name, str) and new_name.strip() else basename(source)
    snapshot = _archive_snapshot(client, source, archive_dir, effective_name)
    return {
        "mode": "plan-only",
        "source": snapshot["source"],
        "archive_dir": snapshot["archive_dir"],
        "new_name": snapshot["new_name"],
        "plan_ref": snapshot["plan_ref"],
        "execute_required": True,
        "ondup": "fail",
        "async": 0,
        "actions": [
            {
                "action": "file_move",
                "path": snapshot["source"],
                "dest": snapshot["archive_dir"],
                "newname": snapshot["new_name"],
                "ondup": "fail",
                "async": 0,
            }
        ],
    }


def execute_archive(
    client: MCPBridge,
    source: str,
    archive_dir: str,
    new_name: str | None,
    plan_ref: str,
) -> dict[str, Any]:
    source = validate_mcp_path(source, allow_root=False)
    effective_name = new_name.strip() if isinstance(new_name, str) and new_name.strip() else basename(source)
    snapshot = _archive_snapshot(client, source, archive_dir, effective_name)
    if snapshot["plan_ref"] != plan_ref:
        raise MCPBridgeError("INVALID_ARG", "archive plan changed; regenerate plan")
    filelist = [
        {
            "path": snapshot["source"],
            "dest": snapshot["archive_dir"],
            "newname": snapshot["new_name"],
        }
    ]
    request = {
        "async": 0,
        "ondup": "fail",
        # The official tool schema declares filelist as a JSON-encoded
        # string, even though the plan presents the same value structurally.
        "filelist": json.dumps(filelist, ensure_ascii=False, separators=(",", ":")),
    }
    client.call("file_move", request)
    source_after = list_directory(client, parent_path(source))
    target_after = list_directory(client, snapshot["archive_dir"])
    source_present = any(item["path"] == source for item in source_after)
    target_matches = [item for item in target_after if item["name"] == snapshot["new_name"]]
    if source_present or len(target_matches) != 1:
        raise MCPBridgeError("PARSE", "file_move postcondition could not be verified")
    return {
        "mode": "execute",
        "source": source,
        "archive_dir": snapshot["archive_dir"],
        "new_name": snapshot["new_name"],
        "plan_ref": plan_ref,
        "postcondition": {
            "status": "verified",
            "source_absent": True,
            "target_present": True,
            "operation": "file_move",
        },
    }
