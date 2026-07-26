"""Tool metadata assembly for LLM tasks."""

from __future__ import annotations

from typing import Any

from pallas.product.llm.kernel import plan_direct_chat_stages
from pallas.product.llm.tools import registry as tool_registry


def assemble_tool_bundle(
    *,
    task: str,
    user_text: str,
    tool_metadata: dict[str, Any] | None = None,
    bot_id: int | None = None,
    group_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    metadata = (
        dict(tool_metadata)
        if tool_metadata is not None
        else tool_registry.tool_metadata_for_chat(
            task=task,
            user_text=user_text,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
        )
    )
    if task == "llm_chat":
        metadata["agent_stage_plan"] = plan_direct_chat_stages(tools_enabled=bool(metadata.get("tools_enabled")))
        metadata["tool_schema_count"] = len(metadata.get("tool_schemas") or [])
    return metadata
