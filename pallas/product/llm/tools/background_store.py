"""Durable records for explicitly backgroundable LLM tools."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext

_RECOVERABLE_STATUSES = frozenset({"pending", "running"})
_TERMINAL_STATUSES = frozenset({"completed", "failed", "timeout"})


def background_tool_tasks_path() -> Path:
    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    root = Path(env_dir) / "pallas_llm" if env_dir else plugin_data_dir("pb_webui", create=True) / "pallas_llm"
    root.mkdir(parents=True, exist_ok=True)
    return root / "background_tool_tasks.json"


def _load_unlocked(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    return [dict(item) for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _save_unlocked(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n")


def _context_matches(task: dict[str, Any], context: ToolInvokeContext) -> bool:
    return (
        int(task.get("bot_id") or 0) == int(context.bot_id)
        and task.get("group_id") == context.group_id
        and int(task.get("user_id") or 0) == int(context.user_id)
    )


def create_background_tool_task(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    context: ToolInvokeContext,
    max_execution_ms: int,
) -> dict[str, Any]:
    path = background_tool_tasks_path()
    now = int(time.time())
    task = {
        "task_id": f"tool-{uuid.uuid4().hex[:12]}",
        "tool_name": str(tool_name or "").strip(),
        "arguments": dict(arguments),
        "bot_id": int(context.bot_id),
        "group_id": context.group_id,
        "user_id": int(context.user_id),
        "approval_granted": context.is_tool_approved(tool_name),
        "status": "pending",
        "result": None,
        "error": "",
        "event_pending": False,
        "created_at": now,
        "started_at": 0,
        "completed_at": 0,
        "max_execution_ms": max(0, int(max_execution_ms)),
    }
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load_unlocked(path)
        rows.append(task)
        _save_unlocked(path, rows)
    return dict(task)


def _update_background_tool_task(task_id: str, mutate) -> dict[str, Any] | None:
    path = background_tool_tasks_path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load_unlocked(path)
        for index, row in enumerate(rows):
            if str(row.get("task_id") or "") != str(task_id):
                continue
            updated = mutate(dict(row))
            rows[index] = updated
            _save_unlocked(path, rows)
            return dict(updated)
    return None


def mark_background_tool_task_running(task_id: str) -> dict[str, Any] | None:
    def mutate(task: dict[str, Any]) -> dict[str, Any]:
        if str(task.get("status") or "") in _RECOVERABLE_STATUSES:
            task["status"] = "running"
            task["started_at"] = int(time.time())
        return task

    return _update_background_tool_task(task_id, mutate)


def complete_background_tool_task(task_id: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    def mutate(task: dict[str, Any]) -> dict[str, Any]:
        ok = bool(raw.get("ok", True))
        result = raw.get("result")
        task["status"] = "completed" if ok else "failed"
        task["result"] = dict(result) if isinstance(result, dict) else {"value": result} if result is not None else None
        task["error"] = str(raw.get("error") or "")
        task["event_pending"] = True
        task["completed_at"] = int(time.time())
        return task

    return _update_background_tool_task(task_id, mutate)


def fail_background_tool_task(task_id: str, *, error: str, timeout: bool = False) -> dict[str, Any] | None:
    def mutate(task: dict[str, Any]) -> dict[str, Any]:
        task["status"] = "timeout" if timeout else "failed"
        task["error"] = str(error or "tool_failed")
        task["event_pending"] = True
        task["completed_at"] = int(time.time())
        return task

    return _update_background_tool_task(task_id, mutate)


def list_recoverable_background_tool_tasks() -> list[dict[str, Any]]:
    path = background_tool_tasks_path()
    return [row for row in _load_unlocked(path) if str(row.get("status") or "") in _RECOVERABLE_STATUSES]


def drain_background_tool_events(context: ToolInvokeContext | None) -> list[dict[str, Any]]:
    if context is None:
        return []
    path = background_tool_tasks_path()
    events: list[dict[str, Any]] = []
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load_unlocked(path)
        changed = False
        for task in rows:
            if (
                str(task.get("status") or "") not in _TERMINAL_STATUSES
                or not task.get("event_pending")
                or not _context_matches(task, context)
            ):
                continue
            events.append({
                "task_id": str(task.get("task_id") or ""),
                "tool": str(task.get("tool_name") or ""),
                "status": str(task.get("status") or "failed"),
                "result": task.get("result") if isinstance(task.get("result"), dict) else None,
                "error": str(task.get("error") or ""),
            })
            task["event_pending"] = False
            task["delivered_at"] = int(time.time())
            changed = True
        if changed:
            _save_unlocked(path, rows)
    return events


def clear_background_tool_tasks() -> None:
    path = background_tool_tasks_path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        _save_unlocked(path, [])
