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


def get_knowledge_source_by_id(
    source_id: str,
    *,
    cfg: LlmConfig | None = None,
) -> RegisteredKnowledgeSource | None:
    sid = (source_id or "").strip()
    if not sid:
        return None
    for row in list_active_knowledge_sources(cfg=cfg):
        if row.source_id == sid:
            return row
    return None


def build_knowledge_source_detail_ui(
    source_id: str,
    *,
    preview_limit: int = 30,
    preview_content_len: int = 240,
    cfg: LlmConfig | None = None,
) -> dict[str, Any] | None:
    """WebUI 只读语料源详情：元数据 + chunk 预览（截断）。"""
    row = get_knowledge_source_by_id(source_id, cfg=cfg)
    if row is None:
        return None
    decl = row.decl
    limit = max(1, min(100, int(preview_limit)))
    content_len = max(32, min(2000, int(preview_content_len)))
    chunks_preview: list[dict[str, Any]] = []
    for index, chunk in enumerate(decl.chunks[:limit]):
        raw = (chunk.content or "").strip()
        preview = raw if len(raw) <= content_len else raw[: content_len - 1].rstrip() + "…"
        chunks_preview.append({
            "index": index,
            "title": (chunk.title or "").strip(),
            "keywords": (chunk.keywords or "").strip(),
            "content_preview": preview,
            "content_len": len(raw),
        })
    return {
        "source_id": row.source_id,
        "title": decl.title,
        "description": decl.description,
        "scope": decl.scope.value,
        "retrieval_mode": decl.retrieval_mode.value,
        "origin": row.origin.value,
        "plugin_name": row.plugin_name,
        "plugin_title": row.plugin_title,
        "default": bool(decl.default),
        "top_k": int(decl.top_k),
        "max_chunk_len": int(decl.max_chunk_len),
        "chunk_count": len(decl.chunks),
        "chunks_preview": chunks_preview,
        "chunks_preview_truncated": len(decl.chunks) > limit,
        "preview_content_len": content_len,
    }


def probe_knowledge_source_retrieve(
    query_text: str,
    *,
    source_id: str | None = None,
    top_k: int | None = None,
    cfg: LlmConfig | None = None,
) -> dict[str, Any] | None:
    """WebUI 检索试探：对单个或全部语料源跑与线上一致的 retrieve。"""
    c = cfg or get_llm_config()
    query = (query_text or "").strip()
    sid = (source_id or "").strip() or None
    min_score = max(0, int(getattr(c, "llm_knowledge_min_score", 0) or 0))
    if not query:
        return {
            "query": "",
            "source_id": sid,
            "min_score": min_score,
            "items": [],
            "count": 0,
            "enabled": can_read_generic_knowledge(c),
        }
    if not can_read_generic_knowledge(c):
        return {
            "query": query,
            "source_id": sid,
            "min_score": min_score,
            "items": [],
            "count": 0,
            "enabled": False,
        }

    if sid:
        row = get_knowledge_source_by_id(sid, cfg=c)
        if row is None:
            return None
        rows = [row]
    else:
        rows = list_active_knowledge_sources(cfg=c)

    items: list[dict[str, Any]] = []
    for row in rows:
        decl = row.decl
        k = min(int(decl.top_k), int(c.llm_knowledge_top_k))
        if top_k is not None:
            k = max(1, min(20, int(top_k)))
        max_len = min(int(decl.max_chunk_len), int(c.llm_knowledge_content_max_len))
        chunks = retrieve_chunks_from_decl(decl, query, top_k=k, max_chunk_len=max_len)
        for chunk in chunks:
            score = int(chunk.score)
            if min_score > 0 and score < min_score:
                continue
            items.append({
                "source_id": row.source_id,
                "title": chunk.title,
                "content": chunk.content,
                "score": score,
                "retrieval_mode": decl.retrieval_mode.value,
            })
    items.sort(key=lambda item: int(item["score"]), reverse=True)
    if sid is None:
        items = items[: max(1, int(c.llm_knowledge_top_k))]
    return {
        "query": query,
        "source_id": sid,
        "min_score": min_score,
        "items": items,
        "count": len(items),
        "enabled": True,
    }


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
    min_score = max(0, int(getattr(c, "llm_knowledge_min_score", 0) or 0))
    if min_score > 0:
        hits = [item for item in hits if int(item.score) >= min_score]
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
