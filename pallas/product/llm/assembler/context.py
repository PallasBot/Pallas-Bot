"""Context assembly entry points for LLM products."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pallas.product.llm.knowledge.inject import enrich_system_with_knowledge_sources
from pallas.product.llm.memory import (
    enrich_system_with_memory_context,
    enrich_system_with_person_facts,
    enrich_system_with_relationship_context,
)
from pallas.product.llm.memory.inject import PersonFactsInjectionResult, RelationshipInjectionResult
from pallas.product.llm.repeater_persona_context import build_repeater_llm_persona_context
from pallas.product.persona.expression_habits import build_expression_context_with_entries


@dataclass(frozen=True)
class DirectChatContext:
    system_prompt: str
    knowledge_retrieval_trace: dict[str, Any]
    hybrid_retrieval_trace: dict[str, Any]
    relationship_trace: dict[str, Any]
    stage_durations_ms: dict[str, int] = field(default_factory=dict)


async def assemble_direct_chat_context(
    system_prompt: str,
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    query_text: str,
    cfg: Any,
    allow_persistent_memory: bool = True,
    allow_expression_reference: bool = True,
) -> DirectChatContext:
    stage_durations_ms: dict[str, int] = {}
    started = time.perf_counter()
    memory_result = await enrich_system_with_memory_context(
        system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        query_text=query_text,
        cfg=cfg,
        allow_persistent_memory=allow_persistent_memory,
    )
    stage_durations_ms["memory"] = int((time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    knowledge_result = await enrich_system_with_knowledge_sources(
        memory_result.system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        query_text=query_text,
        cfg=cfg,
    )
    stage_durations_ms["knowledge"] = int((time.perf_counter() - started) * 1000)
    if allow_persistent_memory:
        started = time.perf_counter()
        relationship_result = await enrich_system_with_relationship_context(
            knowledge_result.system_prompt,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            cfg=cfg,
        )
        stage_durations_ms["relationship"] = int((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        person_facts_result = await enrich_system_with_person_facts(
            relationship_result.system_prompt,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            cfg=cfg,
        )
        stage_durations_ms["person_facts"] = int((time.perf_counter() - started) * 1000)
    else:
        skipped_trace = {"hit_count": 0, "sources": [], "skipped_short_social_turn": True}
        relationship_result = RelationshipInjectionResult(
            system_prompt=knowledge_result.system_prompt,
            trace=skipped_trace,
        )
        person_facts_result = PersonFactsInjectionResult(
            system_prompt=knowledge_result.system_prompt,
            trace=skipped_trace,
        )
        stage_durations_ms["relationship"] = 0
        stage_durations_ms["person_facts"] = 0
    expression_reference = ""
    if allow_expression_reference:
        started = time.perf_counter()
        try:
            expression_reference, _entries = await build_expression_context_with_entries(
                group_id,
                query_text,
                bot_id=bot_id,
                scene="group_chat",
            )
        except Exception:
            expression_reference = ""
        stage_durations_ms["expression"] = int((time.perf_counter() - started) * 1000)
    else:
        stage_durations_ms["expression"] = 0
    system_prompt = person_facts_result.system_prompt
    if expression_reference:
        system_prompt = f"{system_prompt.rstrip()}\n\n{expression_reference}".strip()
    from pallas.product.llm.knowledge.embedding_client import embedding_capability_trace
    from pallas.product.llm.knowledge.vector_backend import vector_retrieve_mode

    capability = {
        "retrieve_mode": vector_retrieve_mode(cfg),
        **embedding_capability_trace(cfg),
    }
    memory_result.trace.update(capability)
    knowledge_result.trace.update(capability)
    hybrid_trace = {
        "retrieve_mode": capability["retrieve_mode"],
        "sources": [
            source
            for source, trace in (
                ("memory", memory_result.trace),
                ("knowledge", knowledge_result.trace),
                ("relationship", relationship_result.trace),
                ("person_facts", person_facts_result.trace),
            )
            if int(trace.get("hit_count") or 0) > 0
        ],
        "memory": memory_result.trace,
        "knowledge": knowledge_result.trace,
        "relationship": relationship_result.trace,
    }
    return DirectChatContext(
        system_prompt=system_prompt,
        knowledge_retrieval_trace=knowledge_result.trace,
        hybrid_retrieval_trace=hybrid_trace,
        relationship_trace=relationship_result.trace,
        stage_durations_ms=stage_durations_ms,
    )


async def assemble_repeater_context(
    bot_id: int,
    group_id: int,
    plain: str,
    **kwargs: Any,
) -> Any:
    return await build_repeater_llm_persona_context(bot_id, group_id, plain, **kwargs)
