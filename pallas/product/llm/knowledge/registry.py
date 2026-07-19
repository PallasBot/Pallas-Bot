"""知识源注册表与检索调度。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.kernel.memory_governance import can_read_generic_knowledge, resolve_memory_read_policy
from pallas.product.llm.knowledge.metadata import iter_loaded_plugin_knowledge_sources
from pallas.product.llm.knowledge.models import (
    KNOWLEDGE_CONTRACT_VERSION,
    KnowledgeRetrievalMode,
    KnowledgeSourceDecl,
    RetrievedKnowledgeChunk,
)
from pallas.product.llm.knowledge.retrieve import retrieve_chunks_from_decl


class KnowledgeSourceOrigin(StrEnum):
    BUILTIN = "builtin"
    PLUGIN = "plugin"


@dataclass(frozen=True)
class RegisteredKnowledgeSource:
    source_id: str
    plugin_name: str
    plugin_title: str
    decl: KnowledgeSourceDecl
    origin: KnowledgeSourceOrigin = KnowledgeSourceOrigin.PLUGIN


_BUILTIN_SOURCES: list[RegisteredKnowledgeSource] = []


def register_builtin_knowledge_source(*, source_id: str, decl: KnowledgeSourceDecl) -> None:
    sid = (source_id or "").strip()
    if not sid or any(row.source_id == sid for row in _BUILTIN_SOURCES):
        return
    _BUILTIN_SOURCES.append(
        RegisteredKnowledgeSource(
            source_id=sid,
            plugin_name="pallas",
            plugin_title="Pallas",
            decl=decl,
            origin=KnowledgeSourceOrigin.BUILTIN,
        )
    )


def list_active_knowledge_sources(*, cfg: LlmConfig | None = None) -> list[RegisteredKnowledgeSource]:
    c = cfg or get_llm_config()
    if not can_read_generic_knowledge(c):
        return []
    try:
        from pallas.product.llm.knowledge.file_ingest import ensure_file_knowledge_registered

        ensure_file_knowledge_registered(cfg=c)
    except Exception as exc:
        logger.warning("knowledge file ingest ensure failed err={}", exc)
    seen = {row.source_id for row in _BUILTIN_SOURCES}
    rows: list[RegisteredKnowledgeSource] = list(_BUILTIN_SOURCES)
    for plugin_name, plugin_title, decl in iter_loaded_plugin_knowledge_sources():
        if decl.source_id in seen:
            continue
        seen.add(decl.source_id)
        rows.append(
            RegisteredKnowledgeSource(
                source_id=decl.source_id,
                plugin_name=plugin_name,
                plugin_title=plugin_title,
                decl=decl,
                origin=KnowledgeSourceOrigin.PLUGIN,
            )
        )
    return rows


def retrieve_from_knowledge_sources(
    query_text: str,
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    cfg: LlmConfig | None = None,
) -> list[RetrievedKnowledgeChunk]:
    c = cfg or get_llm_config()
    if not can_read_generic_knowledge(c):
        return []
    hits: list[RetrievedKnowledgeChunk] = []
    for row in list_active_knowledge_sources(cfg=c):
        decl = row.decl
        if decl.retrieval_mode != KnowledgeRetrievalMode.PROMPT_INJECT:
            continue
        if decl.scope.value == "group" and group_id is None:
            continue
        if decl.scope.value == "user" and not user_id:
            continue
        top_k = min(decl.top_k, c.llm_knowledge_top_k)
        max_len = min(decl.max_chunk_len, c.llm_knowledge_content_max_len)
        chunks = retrieve_chunks_from_decl(
            decl,
            query_text,
            top_k=top_k,
            max_chunk_len=max_len,
        )
        hits.extend(
            RetrievedKnowledgeChunk(
                source_id=row.source_id,
                title=chunk.title,
                content=chunk.content,
                score=chunk.score,
            )
            for chunk in chunks
        )
    hits.sort(key=lambda item: item.score, reverse=True)
    cap = max(1, c.llm_knowledge_top_k)
    return hits[:cap]


def knowledge_metadata_payload(
    trace: dict[str, Any],
    *,
    cfg: LlmConfig | None = None,
) -> dict[str, Any]:
    c = cfg or get_llm_config()
    policy = resolve_memory_read_policy(c)
    return {
        "knowledge_contract_version": KNOWLEDGE_CONTRACT_VERSION,
        "knowledge_policy": {
            "allow_generic_knowledge": policy.allow_generic_knowledge,
            "enabled": can_read_generic_knowledge(c),
        },
        "knowledge_sources": [
            {
                "source_id": row.source_id,
                "title": row.decl.title,
                "retrieval_mode": row.decl.retrieval_mode.value,
                "origin": row.origin.value,
            }
            for row in list_active_knowledge_sources(cfg=c)
        ],
        "retrieval_trace": trace,
    }
