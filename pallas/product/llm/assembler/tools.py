"""Tool metadata assembly for LLM tasks."""

from __future__ import annotations

from typing import Any

from pallas.product.llm.kernel import plan_direct_chat_stages
from pallas.product.llm.tools.registry import tool_metadata_for_chat


def assemble_tool_bundle(
    *,
    task: str,
    user_text: str,
    tool_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = (
        dict(tool_metadata) if tool_metadata is not None else tool_metadata_for_chat(task=task, user_text=user_text)
    )
    if task == "llm_chat":
        metadata["agent_stage_plan"] = plan_direct_chat_stages(tools_enabled=bool(metadata.get("tools_enabled")))
        metadata["tool_schema_count"] = len(metadata.get("tool_schemas") or [])
    return metadata
