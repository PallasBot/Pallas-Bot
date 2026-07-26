"""Context assembly entry points for LLM products."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pallas.product.llm.knowledge.inject import enrich_system_with_knowledge_sources
from pallas.product.llm.memory import (
    enrich_system_with_memory_context,
    enrich_system_with_relationship_context,
)
from pallas.product.llm.repeater_persona_context import build_repeater_llm_persona_context


@dataclass(frozen=True)
class DirectChatContext:
    system_prompt: str
    knowledge_retrieval_trace: dict[str, Any]
    hybrid_retrieval_trace: dict[str, Any]
    relationship_trace: dict[str, Any]


async def assemble_direct_chat_context(
    system_prompt: str,
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    query_text: str,
    cfg: Any,
) -> DirectChatContext:
    memory_result = await enrich_system_with_memory_context(
        system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        query_text=query_text,
        cfg=cfg,
    )
    knowledge_result = await enrich_system_with_knowledge_sources(
        memory_result.system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        query_text=query_text,
        cfg=cfg,
    )
    relationship_result = await enrich_system_with_relationship_context(
        knowledge_result.system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        cfg=cfg,
    )
    hybrid_trace = {
        "sources": [
            source
            for source, trace in (
                ("memory", memory_result.trace),
                ("knowledge", knowledge_result.trace),
                ("relationship", relationship_result.trace),
            )
            if int(trace.get("hit_count") or 0) > 0
        ],
        "memory": memory_result.trace,
        "knowledge": knowledge_result.trace,
        "relationship": relationship_result.trace,
    }
    return DirectChatContext(
        system_prompt=relationship_result.system_prompt,
        knowledge_retrieval_trace=knowledge_result.trace,
        hybrid_retrieval_trace=hybrid_trace,
        relationship_trace=relationship_result.trace,
    )


async def assemble_repeater_context(
    bot_id: int,
    group_id: int,
    plain: str,
    **kwargs: Any,
) -> Any:
    return await build_repeater_llm_persona_context(bot_id, group_id, plain, **kwargs)
