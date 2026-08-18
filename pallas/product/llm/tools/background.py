"""Durable, session-scoped execution for explicitly backgroundable tools."""

from __future__ import annotations

import asyncio
from typing import Any

from pallas.product.llm.tools.background_store import (
    clear_background_tool_tasks,
    complete_background_tool_task,
    create_background_tool_task,
    fail_background_tool_task,
    list_recoverable_background_tool_tasks,
    mark_background_tool_task_running,
)
from pallas.product.llm.tools.background_store import (
    drain_background_tool_events as drain_durable_background_tool_events,
)
from pallas.product.llm.tools.context import ToolInvokeContext

_running: set[asyncio.Task[None]] = set()
_scheduled_task_ids: set[str] = set()


def clear_background_tool_state() -> None:
    for task in tuple(_running):
        task.cancel()
    _running.clear()
    _scheduled_task_ids.clear()
    clear_background_tool_tasks()


def _context_from_task(task: dict[str, Any]) -> ToolInvokeContext:
    tool_name = str(task.get("tool_name") or "")
    approved_tools = frozenset({tool_name}) if task.get("approval_granted") else frozenset()
    return ToolInvokeContext(
        bot_id=int(task.get("bot_id") or 0),
        group_id=task.get("group_id"),
        user_id=int(task.get("user_id") or 0),
        request_id=str(task.get("task_id") or ""),
        approved_tools=approved_tools,
    )


def _background_tool_is_allowed(tool_name: str) -> bool:
    from pallas.product.llm.tools.registry import list_registered_tools

    return any(spec.name == tool_name and spec.background_ok for spec in list_registered_tools())


def _background_tool_recovery_error(task: dict[str, Any]) -> str:
    from pallas.product.llm.tools.contracts import ToolCapability
    from pallas.product.llm.tools.registry import list_registered_tools

    tool_name = str(task.get("tool_name") or "")
    spec = next((item for item in list_registered_tools() if item.name == tool_name), None)
    if spec is None or not spec.background_ok:
        return "background_not_supported"
    if ToolCapability.SIDE_EFFECTING.value not in spec.capabilities:
        return ""
    idempotency_key = str(spec.idempotency_key or "").strip()
    arguments = task.get("arguments") if isinstance(task.get("arguments"), dict) else {}
    if not idempotency_key or not str(arguments.get(idempotency_key) or "").strip():
        return "background_recovery_not_idempotent"
    return ""


def _schedule_background_tool_task(task: dict[str, Any], *, recovery: bool = False) -> bool:
    task_id = str(task.get("task_id") or "")
    tool_name = str(task.get("tool_name") or "")
    if not task_id or task_id in _scheduled_task_ids:
        return False
    if not _background_tool_is_allowed(tool_name):
        fail_background_tool_task(task_id, error="background_not_supported")
        return False
    if recovery:
        recovery_error = _background_tool_recovery_error(task)
        if recovery_error:
            fail_background_tool_task(task_id, error=recovery_error)
            return False
    _scheduled_task_ids.add(task_id)

    async def run() -> None:
        try:
            mark_background_tool_task_running(task_id)
            from pallas.product.llm.tools.registry import execute_tool_async

            context = _context_from_task(task)
            max_execution_ms = int(task.get("max_execution_ms") or 0)
            execute = execute_tool_async(
                tool_name,
                dict(task.get("arguments") or {}),
                context=context,
            )
            result = (
                await asyncio.wait_for(execute, timeout=max(1, max_execution_ms) / 1000)
                if max_execution_ms > 0
                else await execute
            )
            complete_background_tool_task(
                task_id, result if isinstance(result, dict) else {"ok": True, "result": result}
            )
        except TimeoutError:
            fail_background_tool_task(task_id, error="tool_timeout", timeout=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            fail_background_tool_task(task_id, error=str(exc))
        finally:
            _scheduled_task_ids.discard(task_id)

    running = asyncio.create_task(run(), name=f"llm-tool-{task_id}")
    _running.add(running)
    running.add_done_callback(_running.discard)
    return True


def start_background_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    context: ToolInvokeContext,
    max_execution_ms: int,
) -> dict[str, Any]:
    """Persist an allowlisted task before scheduling it; never sends a direct reply."""
    task = create_background_tool_task(
        tool_name=tool_name,
        arguments=arguments,
        context=context,
        max_execution_ms=max_execution_ms,
    )
    _schedule_background_tool_task(task)
    return {"task_id": task["task_id"], "status": "running", "tool": task["tool_name"]}


async def resume_background_tool_tasks() -> int:
    """Schedule durable pending/running tasks through the current tool registry."""
    scheduled = 0
    for task in list_recoverable_background_tool_tasks():
        if _schedule_background_tool_task(task, recovery=True):
            scheduled += 1
    return scheduled


def drain_background_tool_events(context: ToolInvokeContext | None) -> list[dict[str, Any]]:
    """Consume completed events only in their original bot/group/user session."""
    return drain_durable_background_tool_events(context)
