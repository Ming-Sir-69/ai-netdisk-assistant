"""Agent→Agent recovery ledger for every cloud write.

它回答的问题只有一个：**出事之后，凭什么知道文件原来在哪、现在在哪、写完了没有。**

因此每条事件都必须自包含——不依赖上一条、不依赖对话记忆。失败事件还必须同时
带上恢复决策码、CLI 原始状态和唯一下一步，缺一不可，否则下一个 Agent 只能猜。

台账不面向用户展示，也不承载凭证：分享链接、提取码、Token、Cookie 和账号正文
一律先经脱敏再落盘。
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # scripts import modules as top-level; tests import the package
    from common import SKILL_ROOT, redact_value
except ModuleNotFoundError:  # pragma: no cover - exercised by package import
    from .common import SKILL_ROOT, redact_value


# 恢复决策码 → 唯一下一步。两者必须成对出现，避免「记了错误码却没写怎么办」。
RECOVERY_ACTIONS = {
    "JRN-001": "bounded_relocate",
    "JRN-002": "stop_journal_invalid",
    "JRN-003": "bounded_relocate",
    "RCV-001": "stop_state_mismatch",
    "RCV-002": "read_recovery_paths_and_replan",
    "RCV-003": "regenerate_plan",
    "RCV-004": "stop_ambiguous",
    "RCV-005": "stop_postcondition_unverified",
}

REQUIRED_FIELDS = ("run_id", "stage", "attempt", "source_path", "status")

# 这些状态意味着「没有干净地完成」，因此必须带恢复三元组。
UNRESOLVED_STATUSES = {"partial", "failed", "unverified", "ambiguous"}


# 台账的脱敏比全局更严：它一律不存 URL。全局 redact_text 会盖住提取码与
# Token，但会保留链接本身；而分享链接进了台账就等于长期留存，因此这里额外剥掉。
_URL_RE = re.compile(r"(?i)\b(?:https?|ftp)://\S+")


def _scrub(value: Any) -> Any:
    """Recursively strip URLs from an already globally-redacted value."""

    if isinstance(value, str):
        return _URL_RE.sub("[REDACTED-URL]", value)
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


class JournalError(RuntimeError):
    """A journal problem that already carries its own recovery decision."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.next_action = RECOVERY_ACTIONS.get(error_code, "stop_journal_invalid")


def new_run_id() -> str:
    """Return an opaque run identifier that encodes nothing about the user."""

    return secrets.token_hex(16)


def default_path() -> Path:
    configured = os.environ.get("PANLIB_JOURNAL_PATH")
    if configured:
        return Path(configured)
    return Path(SKILL_ROOT) / "runtime" / "journal.jsonl"


def _validated(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("journal event must be a dict")
    missing = [field for field in REQUIRED_FIELDS if event.get(field) in (None, "")]
    if missing:
        raise ValueError("journal event is missing required field(s): " + ", ".join(missing))

    status = str(event["status"])
    error_code = event.get("error_code")
    if status in UNRESOLVED_STATUSES or error_code is not None:
        for field in ("error_code", "original_cli_code", "next_action"):
            if not event.get(field):
                raise ValueError(
                    "an unresolved journal event requires error_code, "
                    "original_cli_code and next_action together; missing " + field
                )
        code = str(event["error_code"])
        if code not in RECOVERY_ACTIONS:
            raise ValueError(f"unknown recovery error_code: {code}")
        expected = RECOVERY_ACTIONS[code]
        if str(event["next_action"]) != expected:
            raise ValueError(
                f"next_action for {code} must be {expected}, got {event['next_action']}"
            )
    return event


def append_event(event: dict[str, Any], *, path: Path | str | None = None) -> Path:
    """Validate, redact and append one event as a single JSON line."""

    validated = _validated(event)
    target = Path(path) if path is not None else default_path()
    record = dict(_scrub(redact_value(validated)))
    record["recorded_at"] = datetime.now(timezone.utc).isoformat()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return target


def read_run(run_id: str, *, path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return one run's events in write order.

    读不到台账不等于「没发生过写入」，所以这里抛出的是带恢复码的错误，
    让调用方走有界重新定位，而不是当作空结果继续。
    """

    target = Path(path) if path is not None else default_path()
    if not target.exists():
        raise JournalError("JRN-001", f"journal not found: {target}")
    events: list[dict[str, Any]] = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise JournalError("JRN-002", f"journal line {number} is not valid JSON") from exc
        if not isinstance(record, dict):
            raise JournalError("JRN-002", f"journal line {number} is not an object")
        if record.get("run_id") == run_id:
            events.append(record)
    if not events:
        raise JournalError("JRN-001", f"no events recorded for run {run_id}")
    return events
