"""群梗/教导记忆：PG 存储与检索。"""

from __future__ import annotations

import time
from typing import Any

from nonebot import logger
from sqlalchemy import delete, func, select

from pallas.core.foundation.db.repository_pg import LlmMemoryEntryRow, get_session, is_pg_initialized
from pallas.core.foundation.db.runtime import is_postgresql_backend
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.policy import classify_memory_candidate, normalize_episode_note
from pallas.product.llm.session_store import normalize_group_scope
from pallas.product.persona.prompt_guard import sanitize_prompt_block, sanitize_prompt_literal


def is_llm_memory_store_available() -> bool:
    cfg = get_llm_config()
    return cfg.llm_memory_rag_enabled and is_postgresql_backend() and is_pg_initialized()


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
    cfg: LlmConfig | None = None,
) -> bool:
    if not is_llm_memory_store_available():
        return False
    c = cfg or get_llm_config()
    safe_content = sanitize_prompt_block(content, max_len=c.llm_memory_content_max_len)
    normalized_source = (source or "").strip()
    if normalized_source in ("teach", "auto_episode", ""):
        kind = classify_memory_candidate(safe_content)
        if normalized_source in ("teach", ""):
            normalized_source = kind or "teach"
        safe_content = normalize_episode_note(safe_content, max_len=c.llm_memory_content_max_len)
        if normalized_source == "auto_episode" and not kind:
            return False
    if not safe_content:
        return False
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    keywords = derive_memory_keywords(safe_content)
    embedding_json: str | None = None
    embedding_model: str | None = None
    if c.llm_vector_retrieve != "keyword":
        from pallas.product.llm.knowledge.embedding_client import embedding_model_name, fetch_embeddings_sync
        from pallas.product.llm.memory.retrieve import dump_embedding_json, memory_embedding_text

        text = memory_embedding_text(keywords=keywords, content=safe_content)
        vectors = fetch_embeddings_sync([text]) if text.strip() else None
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


async def retrieve_memory_hits(
    bot_id: int,
    group_id: int | None,
    query_text: str,
    *,
    cfg: LlmConfig | None = None,
) -> list[dict[str, Any]]:
    if not is_llm_memory_store_available():
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
    from pallas.product.llm.memory.retrieve import dump_embedding_json, rank_memory_candidates

    candidates = [
        {
            "id": int(row.id),
            "content": str(row.content or "").strip(),
            "keywords": str(row.keywords or "").strip(),
            "source": str(row.source or "").strip() or "memory",
            "group_id": int(row.group_id or 0),
            "embedding_json": getattr(row, "embedding_json", None),
            "embedding_model": getattr(row, "embedding_model", None),
        }
        for row in rows
    ]
    scored = rank_memory_candidates(
        query_text,
        candidates,
        embedding_model=embedding_model_name(c),
    )
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
            logger.warning("memory embedding cache persist failed err={}", exc)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in scored:
        content = str(item.get("content") or "").strip()
        if not content or content in seen:
            continue
        seen.add(content)
        out.append(item)
        if len(out) >= min(top_k, 3):
            break
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
            "created_at": int(row.created_at or 0),
            "updated_at": int(row.updated_at or 0),
        })
        if len(items) >= max_limit:
            break
    return items


async def delete_memory_entry(entry_id: int, *, bot_id: int | None = None) -> bool:
    if not is_llm_memory_store_available():
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
