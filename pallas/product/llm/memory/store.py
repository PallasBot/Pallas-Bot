"""群梗/教导记忆：PG / Mongo 存储与检索。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from nonebot import logger
from sqlalchemy import delete, func, select

from pallas.core.foundation.db.repository_pg import LlmMemoryEntryRow, get_session
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.policy import classify_memory_candidate, normalize_episode_note
from pallas.product.llm.session_backend import llm_product_storage_ready
from pallas.product.llm.session_store import normalize_group_scope
from pallas.product.persona.prompt_guard import sanitize_prompt_block, sanitize_prompt_literal


def is_llm_memory_store_available() -> bool:
    cfg = get_llm_config()
    return cfg.llm_memory_rag_enabled and llm_product_storage_ready()


def _use_mongodb_backend() -> bool:
    from pallas.core.foundation.db.runtime import is_mongodb_backend

    return is_mongodb_backend()


def _use_postgresql_backend() -> bool:
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    return is_postgresql_backend()


def derive_memory_keywords(content: str, *, max_len: int = 120) -> str:
    from pallas.product.llm.memory.retrieve import tokenize_for_memory

    tokens = sorted(tokenize_for_memory(content), key=len, reverse=True)
    picked: list[str] = []
    total = 0
    for token in tokens:
        if token in picked:
            continue
        if total + len(token) + (1 if picked else 0) > max_len:
            break
        picked.append(token)
        total += len(token) + (1 if picked else 0)
    return ",".join(picked[:12])


def canonicalize_memory_content(content: str) -> str:
    text = (content or "").strip()
    return text.rstrip("。！？!?；;，,、")


def derive_memory_metadata(
    *,
    group_id: int | None,
    source: str,
    importance: float | None = None,
    confidence: float | None = None,
    expires_at: int = 0,
    visibility: str | None = None,
) -> dict[str, float | int | str]:
    source_defaults = {
        "teach": (0.8, 0.9),
        "auto_episode": (0.3, 0.4),
        "auto_episode_summary": (0.5, 0.6),
        "auto_ip_knowledge": (0.6, 0.7),
    }
    default_importance, default_confidence = source_defaults.get((source or "").strip(), (0.5, 0.5))

    def bounded(value: float | None, default: float) -> float:
        try:
            return max(0.0, min(float(value if value is not None else default), 1.0))
        except (TypeError, ValueError):
            return default

    scope_gid = normalize_group_scope(group_id)
    normalized_visibility = str(visibility or ("private" if scope_gid == 0 else "group")).strip().lower()
    if normalized_visibility not in {"private", "group", "bot_global"}:
        normalized_visibility = "private" if scope_gid == 0 else "group"
    try:
        normalized_expiry = max(0, int(expires_at or 0))
    except (TypeError, ValueError):
        normalized_expiry = 0
    return {
        "importance": bounded(importance, default_importance),
        "confidence": bounded(confidence, default_confidence),
        "expires_at": normalized_expiry,
        "visibility": normalized_visibility,
    }


def memory_lifecycle_overlay(entry_id: int) -> dict[str, Any]:
    from pallas.product.llm.memory.ops import memory_lifecycle_overlay as get_overlay

    return get_overlay(entry_id)


def apply_memory_lifecycle_overlay(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.memory.retrieve import memory_time_decay_factor

    cfg = get_llm_config()
    half_life = float(getattr(cfg, "llm_memory_decay_half_life_days", 0.0) or 0.0)
    min_importance = float(getattr(cfg, "llm_memory_decay_min_importance", 0.6) or 0.6)
    now = time.time()
    updated: list[dict[str, Any]] = []
    for item in candidates:
        entry_id = item.get("id")
        overlay = memory_lifecycle_overlay(int(entry_id)) if entry_id is not None else {}
        if overlay.get("frozen"):
            continue
        result = dict(item)
        decay_base = item.get("updated_at") or item.get("created_at") or 0
        decay = memory_time_decay_factor(
            decay_base,
            half_life_days=half_life,
            min_importance=min_importance,
            importance=item.get("importance"),
            now=now,
        )
        result["score"] = round(float(result.get("score") or 0) * float(overlay.get("weight") or 1.0) * decay)
        updated.append(result)
    return sorted(updated, key=lambda candidate: float(candidate.get("score") or 0), reverse=True)


def memory_entries_semantically_match(left: str, right: str) -> bool:
    lhs = canonicalize_memory_content(left)
    rhs = canonicalize_memory_content(right)
    return bool(lhs and rhs and lhs == rhs)


async def find_reusable_memory_entry(
    session,
    *,
    bot_id: int,
    group_id: int,
    safe_content: str,
    keywords: str,
) -> LlmMemoryEntryRow | None:
    exact = (
        await session.execute(
            select(LlmMemoryEntryRow).where(
                LlmMemoryEntryRow.bot_id == bot_id,
                LlmMemoryEntryRow.group_id == group_id,
                LlmMemoryEntryRow.content == safe_content,
            )
        )
    ).scalar_one_or_none()
    if exact is not None:
        return exact

    rows = (
        (
            await session.execute(
                select(LlmMemoryEntryRow)
                .where(
                    LlmMemoryEntryRow.bot_id == bot_id,
                    LlmMemoryEntryRow.group_id == group_id,
                )
                .order_by(LlmMemoryEntryRow.updated_at.desc(), LlmMemoryEntryRow.id.desc())
                .limit(32)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if memory_entries_semantically_match(str(row.content or ""), safe_content):
            return row
        row_keywords = str(row.keywords or "")
        row_content = canonicalize_memory_content(str(row.content or ""))
        if keywords and row_keywords and row_keywords == keywords and row_content:
            return row
    return None


async def save_memory_entry(
    bot_id: int,
    group_id: int | None,
    content: str,
    *,
    source: str = "teach",
    importance: float | None = None,
    confidence: float | None = None,
    expires_at: int = 0,
    visibility: str | None = None,
    cfg: LlmConfig | None = None,
) -> bool:
    if not is_llm_memory_store_available():
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.store_mongo import save_memory_entry_mongo

        return await save_memory_entry_mongo(
            bot_id,
            group_id,
            content,
            source=source,
            importance=importance,
            confidence=confidence,
            expires_at=expires_at,
            visibility=visibility,
            cfg=cfg,
        )
    if not _use_postgresql_backend():
        return False
    c = cfg or get_llm_config()
    safe_content = sanitize_prompt_block(content, max_len=c.llm_memory_content_max_len)
    normalized_source = (source or "").strip()
    if normalized_source in ("teach", "auto_episode", "auto_episode_summary", ""):
        kind = classify_memory_candidate(safe_content)
        if normalized_source in ("teach", ""):
            normalized_source = kind or "teach"
        safe_content = normalize_episode_note(safe_content, max_len=c.llm_memory_content_max_len)
        if normalized_source in ("auto_episode", "auto_episode_summary") and not kind:
            return False
    if not safe_content:
        return False
    scope_gid = normalize_group_scope(group_id)
    metadata = derive_memory_metadata(
        group_id=group_id,
        source=source,
        importance=importance,
        confidence=confidence,
        expires_at=expires_at,
        visibility=visibility,
    )
    now = int(time.time())
    keywords = derive_memory_keywords(safe_content)
    embedding_json: str | None = None
    embedding_model: str | None = None
    from pallas.product.llm.knowledge.vector_backend import vector_retrieve_mode

    if vector_retrieve_mode(c) != "keyword":
        from pallas.product.llm.knowledge.embedding_client import (
            EMBEDDING_QUERY_TIMEOUT_SEC,
            embedding_model_name,
            fetch_embeddings_sync,
        )
        from pallas.product.llm.memory.retrieve import dump_embedding_json, memory_embedding_text

        text = memory_embedding_text(keywords=keywords, content=safe_content)
        vectors = (
            await asyncio.to_thread(fetch_embeddings_sync, [text], timeout_sec=EMBEDDING_QUERY_TIMEOUT_SEC)
            if text.strip()
            else None
        )
        if vectors and len(vectors) == 1:
            embedding_json = dump_embedding_json(vectors[0])
            embedding_model = embedding_model_name(c)
    async with get_session() as session:
        safe_source = sanitize_prompt_literal(normalized_source, max_len=16) or "teach"
        existing = await find_reusable_memory_entry(
            session,
            bot_id=int(bot_id),
            group_id=scope_gid,
            safe_content=safe_content,
            keywords=keywords,
        )
        if existing is not None:
            existing.keywords = keywords
            existing.content = safe_content
            existing.source = safe_source
            existing.importance = float(metadata["importance"])
            existing.confidence = float(metadata["confidence"])
            existing.expires_at = int(metadata["expires_at"])
            existing.visibility = str(metadata["visibility"])
            existing.updated_at = now
            if embedding_json is not None:
                existing.embedding_json = embedding_json
                existing.embedding_model = embedding_model
        else:
            session.add(
                LlmMemoryEntryRow(
                    bot_id=int(bot_id),
                    group_id=scope_gid,
                    keywords=keywords,
                    content=safe_content,
                    source=safe_source,
                    importance=float(metadata["importance"]),
                    confidence=float(metadata["confidence"]),
                    expires_at=int(metadata["expires_at"]),
                    visibility=str(metadata["visibility"]),
                    embedding_json=embedding_json,
                    embedding_model=embedding_model,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
        await trim_group_memory_entries(
            session,
            bot_id=int(bot_id),
            group_id=scope_gid,
            max_entries=c.llm_memory_max_per_group,
        )
        await session.commit()
    return True


async def trim_group_memory_entries(
    session,
    *,
    bot_id: int,
    group_id: int,
    max_entries: int,
) -> None:
    if max_entries <= 0:
        return
    count = (
        await session.execute(
            select(func.count())
            .select_from(LlmMemoryEntryRow)
            .where(
                LlmMemoryEntryRow.bot_id == bot_id,
                LlmMemoryEntryRow.group_id == group_id,
            )
        )
    ).scalar_one()
    overflow = int(count) - max_entries
    if overflow <= 0:
        return
    stale_ids = (
        (
            await session.execute(
                select(LlmMemoryEntryRow.id)
                .where(
                    LlmMemoryEntryRow.bot_id == bot_id,
                    LlmMemoryEntryRow.group_id == group_id,
                )
                .order_by(LlmMemoryEntryRow.updated_at.asc(), LlmMemoryEntryRow.id.asc())
                .limit(overflow)
            )
        )
        .scalars()
        .all()
    )
    if stale_ids:
        await session.execute(delete(LlmMemoryEntryRow).where(LlmMemoryEntryRow.id.in_(stale_ids)))


async def retrieve_memory_entries(
    bot_id: int,
    group_id: int | None,
    query_text: str,
    *,
    cfg: LlmConfig | None = None,
) -> list[str]:
    hits = await retrieve_memory_hits(
        bot_id,
        group_id,
        query_text,
        cfg=cfg,
    )
    return [str(item.get("content") or "").strip() for item in hits]


async def touch_memory_hit_timestamps(
    entry_ids: list[object],
    *,
    cfg: LlmConfig | None = None,
) -> None:
    """检索命中后刷新 updated_at（冷却内不重复），使半衰期衰减以最近命中为基准。"""
    ids = [int(item) for item in entry_ids if str(item or "").isdigit() and int(item) > 0]
    if not ids:
        return
    c = cfg or get_llm_config()
    if not getattr(c, "llm_memory_hit_boost_enabled", True):
        return
    boost_sec = max(0, int(getattr(c, "llm_memory_hit_boost_sec", 3600) or 0))
    now = int(time.time())
    try:
        async with get_session() as session:
            for entry_id in ids:
                row = await session.get(LlmMemoryEntryRow, entry_id)
                if row is None:
                    continue
                # 冷却内（boost_sec 秒内已强化过）跳过，避免高频对话反复刷新
                if boost_sec > 0 and (now - int(row.updated_at or 0)) < boost_sec:
                    continue
                row.updated_at = now
            await session.commit()
    except Exception as exc:
        logger.debug("Memory hit timestamp touch skipped: {}", exc)


async def retrieve_memory_hits(
    bot_id: int,
    group_id: int | None,
    query_text: str,
    *,
    cfg: LlmConfig | None = None,
) -> list[dict[str, Any]]:
    if not is_llm_memory_store_available():
        return []
    if _use_mongodb_backend():
        from pallas.product.llm.memory.store_mongo import retrieve_memory_hits_mongo

        return await retrieve_memory_hits_mongo(bot_id, group_id, query_text, cfg=cfg)
    if not _use_postgresql_backend():
        return []
    c = cfg or get_llm_config()
    scope_gid = normalize_group_scope(group_id)
    top_k = max(1, min(int(c.llm_memory_rag_top_k), 8))
    async with get_session(read_only=True) as session:
        rows = (
            (
                await session.execute(
                    select(LlmMemoryEntryRow)
                    .where(
                        LlmMemoryEntryRow.bot_id == int(bot_id),
                        LlmMemoryEntryRow.group_id.in_([scope_gid, 0]),
                    )
                    .order_by(LlmMemoryEntryRow.updated_at.desc(), LlmMemoryEntryRow.id.desc())
                    .limit(max(50, top_k * 10))
                )
            )
            .scalars()
            .all()
        )
    from pallas.product.llm.knowledge.embedding_client import embedding_model_name
    from pallas.product.llm.memory.retrieve import (
        dump_embedding_json,
        effective_memory_rag_min_score,
        filter_memory_candidates_for_scope,
        rank_memory_candidates,
    )

    candidates = [
        {
            "id": int(row.id),
            "content": str(row.content or "").strip(),
            "keywords": str(row.keywords or "").strip(),
            "source": str(row.source or "").strip() or "memory",
            "bot_id": int(row.bot_id),
            "group_id": int(row.group_id or 0),
            "importance": float(getattr(row, "importance", 0.5) or 0.5),
            "confidence": float(getattr(row, "confidence", 0.5) or 0.5),
            "expires_at": int(getattr(row, "expires_at", 0) or 0),
            "visibility": str(getattr(row, "visibility", "") or ""),
            "created_at": int(row.created_at or 0),
            "updated_at": int(row.updated_at or 0),
            "embedding_json": getattr(row, "embedding_json", None),
            "embedding_model": getattr(row, "embedding_model", None),
        }
        for row in rows
    ]
    candidates = filter_memory_candidates_for_scope(
        candidates,
        bot_id=int(bot_id),
        group_id=group_id,
        now=int(time.time()),
    )
    # rank 内会请求 embedding，同步执行会阻塞事件循环，移到线程
    scored = await asyncio.to_thread(
        rank_memory_candidates,
        query_text,
        candidates,
        embedding_model=embedding_model_name(c),
    )
    scored = apply_memory_lifecycle_overlay(scored)
    dirty = [item for item in scored if item.get("embedding_dirty") and item.get("id") and item.get("embedding")]
    if dirty:
        try:
            async with get_session() as session:
                for item in dirty:
                    row = await session.get(LlmMemoryEntryRow, int(item["id"]))
                    if row is None:
                        continue
                    row.embedding_json = dump_embedding_json(list(item["embedding"]))
                    row.embedding_model = str(item.get("embedding_model") or embedding_model_name(c))
                await session.commit()
        except Exception as exc:
            logger.warning("Memory embedding cache persistence failed: [{}]", exc)
    min_score = effective_memory_rag_min_score(c)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in scored:
        content = str(item.get("content") or "").strip()
        if not content or content in seen:
            continue
        if int(item.get("score") or 0) < min_score:
            continue
        seen.add(content)
        out.append(item)
        if len(out) >= top_k:
            break
    await touch_memory_hit_timestamps([item.get("id") for item in out], cfg=c)
    return out


async def list_memory_entries(
    bot_id: int,
    group_id: int | None,
    *,
    query: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not is_llm_memory_store_available():
        return []
    if _use_mongodb_backend():
        from pallas.product.llm.memory.store_mongo import list_memory_entries_mongo

        return await list_memory_entries_mongo(bot_id, group_id, query=query, limit=limit)
    if not _use_postgresql_backend():
        return []
    max_limit = max(1, min(int(limit), 200))
    async with get_session(read_only=True) as session:
        stmt = select(LlmMemoryEntryRow).where(LlmMemoryEntryRow.bot_id == int(bot_id))
        # group_id 未传：按 Bot 全量（与控制台「全部范围」一致）；传入则限定该群
        if group_id is not None:
            stmt = stmt.where(LlmMemoryEntryRow.group_id == normalize_group_scope(group_id))
        rows = (
            (
                await session.execute(
                    stmt.order_by(LlmMemoryEntryRow.updated_at.desc(), LlmMemoryEntryRow.id.desc()).limit(max_limit * 4)
                )
            )
            .scalars()
            .all()
        )
    needle = str(query or "").strip().casefold()
    items: list[dict[str, Any]] = []
    for row in rows:
        content = str(row.content or "").strip()
        keywords = str(row.keywords or "").strip()
        if needle and needle not in content.casefold() and needle not in keywords.casefold():
            continue
        items.append({
            "id": int(row.id),
            "bot_id": int(row.bot_id),
            "group_id": int(row.group_id),
            "keywords": keywords,
            "content": content,
            "source": str(row.source or "").strip() or "teach",
            "importance": float(getattr(row, "importance", 0.5) or 0.5),
            "confidence": float(getattr(row, "confidence", 0.5) or 0.5),
            "expires_at": int(getattr(row, "expires_at", 0) or 0),
            "visibility": str(getattr(row, "visibility", "") or "")
            or ("private" if int(row.group_id or 0) == 0 else "group"),
            "created_at": int(row.created_at or 0),
            "updated_at": int(row.updated_at or 0),
        })
        if len(items) >= max_limit:
            break
    return items


async def delete_memory_entry(entry_id: int, *, bot_id: int | None = None) -> bool:
    if not is_llm_memory_store_available():
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.store_mongo import delete_memory_entry_mongo

        return await delete_memory_entry_mongo(entry_id, bot_id=bot_id)
    if not _use_postgresql_backend():
        return False
    async with get_session() as session:
        row = (
            await session.execute(
                select(LlmMemoryEntryRow).where(
                    LlmMemoryEntryRow.id == int(entry_id),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id or 0) != int(bot_id):
            return False
        await session.delete(row)
        await session.commit()
    return True
