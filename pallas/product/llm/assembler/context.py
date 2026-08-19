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


@dataclass(frozen=True)
class ChatContextBundle:
    """Retrieved reference blocks kept separate until prompt assembly."""

    memory: str = ""
    group_timeline: str = ""
    knowledge: str = ""
    relationship: str = ""
    person_facts: str = ""
    mid_term: str = ""
    knowledge_retrieval_trace: dict[str, Any] = field(default_factory=dict)
    hybrid_retrieval_trace: dict[str, Any] = field(default_factory=dict)
    relationship_trace: dict[str, Any] = field(default_factory=dict)
    stage_durations_ms: dict[str, int] = field(default_factory=dict)

    def blocks(self) -> list[str]:
        return [self.group_timeline, self.memory, self.knowledge, self.relationship, self.person_facts, self.mid_term]


async def assemble_direct_chat_context(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    query_text: str,
    cfg: Any,
    allow_persistent_memory: bool = True,
    group_timeline: str = "",
) -> ChatContextBundle:
    """Retrieve each context source without deciding prompt order or layout."""

    stage_durations_ms: dict[str, int] = {}
    started = time.perf_counter()
    memory_result = await enrich_system_with_memory_context(
        "",
        bot_id=bot_id,
        group_id=group_id,
        query_text=query_text,
        cfg=cfg,
        allow_persistent_memory=allow_persistent_memory,
    )
    stage_durations_ms["memory"] = int((time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    knowledge_result = await enrich_system_with_knowledge_sources(
        "",
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        query_text=query_text,
        cfg=cfg,
    )
    stage_durations_ms["knowledge"] = int((time.perf_counter() - started) * 1000)
    if group_id is not None and user_id:
        started = time.perf_counter()
        relationship_result = await enrich_system_with_relationship_context(
            "",
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            cfg=cfg,
            include_fallback=allow_persistent_memory,
        )
        stage_durations_ms["relationship"] = int((time.perf_counter() - started) * 1000)
    else:
        relationship_result = RelationshipInjectionResult(
            system_prompt="",
            trace={"hit_count": 0, "sources": [], "entries": [], "fallback": False},
        )
        stage_durations_ms["relationship"] = 0
    if allow_persistent_memory:
        started = time.perf_counter()
        person_facts_result = await enrich_system_with_person_facts(
            "",
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            cfg=cfg,
        )
        stage_durations_ms["person_facts"] = int((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        mid_term_block = await recall_mid_term_block(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            query_text=query_text,
        )
        stage_durations_ms["mid_term"] = int((time.perf_counter() - started) * 1000)
    else:
        skipped_trace = {"hit_count": 0, "sources": [], "skipped_short_social_turn": True}
        person_facts_result = PersonFactsInjectionResult(system_prompt="", trace=skipped_trace)
        stage_durations_ms["person_facts"] = 0
        mid_term_block = ""
        stage_durations_ms["mid_term"] = 0
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
    return ChatContextBundle(
        memory=memory_result.system_prompt,
        group_timeline=group_timeline,
        knowledge=knowledge_result.system_prompt,
        relationship=relationship_result.system_prompt,
        person_facts=person_facts_result.system_prompt,
        mid_term=mid_term_block,
        knowledge_retrieval_trace=knowledge_result.trace,
        hybrid_retrieval_trace=hybrid_trace,
        relationship_trace=relationship_result.trace,
        stage_durations_ms=stage_durations_ms,
    )


async def recall_mid_term_block(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    query_text: str,
) -> str:
    """按当前话题召回历史会话摘要，拼成「【相关旧话题】」注入块。"""
    from pallas.product.llm.memory.mid_term import recall_related_mid_term_summaries

    recalled = await recall_related_mid_term_summaries(
        bot_id=int(bot_id),
        group_id=group_id,
        user_id=int(user_id),
        query_text=query_text,
    )
    if not recalled:
        return ""
    lines = ["【相关旧话题】", "- 以下来自更早的对话摘要，仅在话题相关时参考："]
    for item in recalled[:3]:
        body = str(item.get("summary") or "").strip()
        if body:
            lines.append(f"- {body[:160]}")
    return "\n".join(lines)
