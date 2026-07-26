"""人物关系档案工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.product.llm.memory.relationship_store import retrieve_relationship_profile, save_relationship_note
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


def register_person_tools() -> None:
    base = frozenset({ToolCapability.REQUIRES_GROUP_CONTEXT.value})
    register_tool(
        LlmToolSpec(
            name="person.profile.query",
            description="查询群内某用户的人物事实档案。",
            parameters={"type": "object", "properties": {"user_id": {"type": "integer"}}, "required": ["user_id"]},
            domains=frozenset({"person", "memory"}),
            handler=handle_person_profile_query,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}) | base,
        )
    )
    register_tool(
        LlmToolSpec(
            name="person.profile.correct",
            description="提交对群内用户人物事实的更正。",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "fact": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["user_id", "fact"],
            },
            domains=frozenset({"person", "memory"}),
            handler=handle_person_profile_correct,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}) | base,
            approval_required=True,
        )
    )


async def handle_person_profile_query(
    arguments: dict[str, Any], context: ToolInvokeContext | None = None
) -> dict[str, Any]:
    if context is None or context.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    user_id = int((arguments or {}).get("user_id") or context.user_id)
    profile = await retrieve_relationship_profile(context.bot_id, context.group_id, user_id)
    if profile is None:
        return {"ok": True, "result": {"user_id": user_id, "facts": []}}
    return {
        "ok": True,
        "result": {
            "user_id": user_id,
            "profile": profile.model_dump(mode="json") if hasattr(profile, "model_dump") else vars(profile),
        },
    }


async def handle_person_profile_correct(
    arguments: dict[str, Any], context: ToolInvokeContext | None = None
) -> dict[str, Any]:
    if context is None or context.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    fact = str((arguments or {}).get("fact") or "").strip()
    if not fact:
        return {"ok": False, "error": "fact_required"}
    user_id = int((arguments or {}).get("user_id") or context.user_id)
    ok = await save_relationship_note(context.bot_id, context.group_id, user_id, fact, source="llm_correction")
    return {"ok": bool(ok), "result": {"status": str((arguments or {}).get("status") or "candidate")}}
