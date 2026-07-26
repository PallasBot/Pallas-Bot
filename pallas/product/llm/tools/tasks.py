from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.product.llm.orchestration.task_store import cancel_task, create_task, get_task
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


def register_task_tools() -> None:
    register_tool(
        LlmToolSpec(
            name="task.create",
            description="创建一个可追踪的后台任务。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "payload": {"type": "object"},
                    "run_at": {"type": "integer"},
                },
                "required": ["name"],
            },
            domains=frozenset({"task", "chat"}),
            handler=handle_task_create,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value, ToolCapability.BACKGROUND_TASK.value}),
            approval_required=True,
            background_ok=True,
        )
    )
    register_tool(
        LlmToolSpec(
            name="task.cancel",
            description="取消一个后台任务。",
            parameters={"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
            domains=frozenset({"task"}),
            handler=handle_task_cancel,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value, ToolCapability.BACKGROUND_TASK.value}),
            approval_required=True,
        )
    )
    register_tool(
        LlmToolSpec(
            name="task.status",
            description="查看后台任务状态。",
            parameters={"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
            domains=frozenset({"task"}),
            handler=handle_task_status,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}),
        )
    )


async def handle_task_create(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    name = str((arguments or {}).get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name_required"}
    task = create_task(
        name,
        (arguments or {}).get("payload"),
        group_id=getattr(context, "group_id", None),
        user_id=getattr(context, "user_id", None),
        run_at=(arguments or {}).get("run_at"),
    )
    return {"ok": True, "result": task.model_dump(mode="json")}


async def handle_task_cancel(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    del context
    task = cancel_task(str((arguments or {}).get("task_id") or ""))
    return {
        "ok": task is not None,
        "error": "" if task else "task_not_found",
        "result": task.model_dump(mode="json") if task else None,
    }


async def handle_task_status(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    del context
    task = get_task(str((arguments or {}).get("task_id") or ""))
    return {
        "ok": task is not None,
        "error": "" if task else "task_not_found",
        "result": task.model_dump(mode="json") if task else None,
    }
