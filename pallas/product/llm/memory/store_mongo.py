from __future__ import annotations

import time
from typing import Any

from beanie import SortDirection
from nonebot import logger
from pymongo.errors import DuplicateKeyError

from pallas.core.foundation.db.modules import LlmMemoryEntry
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.policy import classify_memory_candidate, normalize_episode_note
from pallas.product.llm.memory.store import (
    canonicalize_memory_content,
    derive_memory_keywords,
    memory_entries_semantically_match,
)
from pallas.product.llm.mongo_id import allocate_mongo_int_id
from pallas.product.llm.session_models import normalize_group_scope
from pallas.product.persona.prompt_guard import sanitize_prompt_block, sanitize_prompt_literal

_MEMORY_ID_INSERT_RETRIES = 8


async def _peek_max_memory_entry_id() -> int:
    rows = await LlmMemoryEntry.find_all().sort([("entry_id", SortDirection.DESCENDING)]).limit(1).to_list()
    if not rows:
        return 0
    return int(rows[0].entry_id or 0)


async def next_memory_entry_id() -> int:
    return await allocate_mongo_int_id("llm_memory_entry", peek_max=_peek_max_memory_entry_id)


async def find_reusable_memory_entry_mongo(
    *,
    bot_id: int,
    group_id: int,
    safe_content: str,
    keywords: str,
) -> LlmMemoryEntry | None:
    exact = await LlmMemoryEntry.find_one({
        "bot_id": bot_id,
        "group_id": group_id,
        "content": safe_content,
    })
    if exact is not None:
        return exact

    rows = (
        await LlmMemoryEntry
        .find({"bot_id": bot_id, "group_id": group_id})
        .sort([("updated_at", SortDirection.DESCENDING), ("entry_id", SortDirection.DESCENDING)])
        .limit(32)
        .to_list()
    )
    for row in rows:
        if memory_entries_semantically_match(str(row.content or ""), safe_content):
            return row
        row_keywords = str(row.keywords or "")
        row_content = canonicalize_memory_content(str(row.content or ""))
        if keywords and row_keywords and row_keywords == keywords and row_content:
            return row
    return None


async def trim_group_memory_entries_mongo(
    *,
    bot_id: int,
    group_id: int,
    max_entries: int,
) -> None:
    if max_entries <= 0:
        return
    query = {"bot_id": bot_id, "group_id": group_id}
    count = await LlmMemoryEntry.find(query).count()
    overflow = int(count) - max_entries
    if overflow <= 0:
        return
    stale = (
        await LlmMemoryEntry
        .find(query)
        .sort([("updated_at", SortDirection.ASCENDING), ("entry_id", SortDirection.ASCENDING)])
        .limit(overflow)
        .to_list()
    )
    for row in stale:
        await row.delete()


async def save_memory_entry_mongo(
    bot_id: int,
    group_id: int | None,
    content: str,
    *,
    source: str = "teach",
    cfg: LlmConfig | None = None,
) -> bool:
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

    safe_source = sanitize_prompt_literal(normalized_source, max_len=16) or "teach"
    existing = await find_reusable_memory_entry_mongo(
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
        await existing.save()
    else:
        inserted = False
        for _ in range(_MEMORY_ID_INSERT_RETRIES):
            try:
                await LlmMemoryEntry(
                    entry_id=await next_memory_entry_id(),
                    bot_id=int(bot_id),
                    group_id=scope_gid,
                    keywords=keywords,
                    content=safe_content,
                    source=safe_source,
                    embedding_json=embedding_json,
                    embedding_model=embedding_model,
                    created_at=now,
                    updated_at=now,
                ).insert()
                inserted = True
                break
            except DuplicateKeyError:
                continue
        if not inserted:
            logger.warning("llm memory insert failed after duplicate entry_id retries")
            return False
    await trim_group_memory_entries_mongo(
        bot_id=int(bot_id),
        group_id=scope_gid,
        max_entries=c.llm_memory_max_per_group,
    )
    return True


async def retrieve_memory_hits_mongo(
    bot_id: int,
    group_id: int | None,
    query_text: str,
    *,
    cfg: LlmConfig | None = None,
) -> list[dict[str, Any]]:
    c = cfg or get_llm_config()
    scope_gid = normalize_group_scope(group_id)
    top_k = max(1, min(int(c.llm_memory_rag_top_k), 8))
    rows = (
        await LlmMemoryEntry
        .find({
            "bot_id": int(bot_id),
            "group_id": {"$in": [scope_gid, 0]},
        })
        .sort([("updated_at", SortDirection.DESCENDING), ("entry_id", SortDirection.DESCENDING)])
        .limit(max(50, top_k * 10))
        .to_list()
    )
    from pallas.product.llm.knowledge.embedding_client import embedding_model_name
    from pallas.product.llm.memory.retrieve import dump_embedding_json, rank_memory_candidates

    candidates = [
        {
            "id": int(row.entry_id),
            "content": str(row.content or "").strip(),
            "keywords": str(row.keywords or "").strip(),
            "source": str(row.source or "").strip() or "memory",
            "group_id": int(row.group_id or 0),
            "embedding_json": row.embedding_json,
            "embedding_model": row.embedding_model,
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
            for item in dirty:
                row = await LlmMemoryEntry.find_one({"entry_id": int(item["id"])})
                if row is None:
                    continue
                row.embedding_json = dump_embedding_json(list(item["embedding"]))
                row.embedding_model = str(item.get("embedding_model") or embedding_model_name(c))
                await row.save()
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


async def list_memory_entries_mongo(
    bot_id: int,
    group_id: int | None,
    *,
    query: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    max_limit = max(1, min(int(limit), 200))
    filt: dict[str, Any] = {"bot_id": int(bot_id)}
    if group_id is not None:
        filt["group_id"] = normalize_group_scope(group_id)
    rows = (
        await LlmMemoryEntry
        .find(filt)
        .sort([("updated_at", SortDirection.DESCENDING), ("entry_id", SortDirection.DESCENDING)])
        .limit(max_limit * 4)
        .to_list()
    )
    needle = str(query or "").strip().casefold()
    items: list[dict[str, Any]] = []
    for row in rows:
        content = str(row.content or "").strip()
        keywords = str(row.keywords or "").strip()
        if needle and needle not in content.casefold() and needle not in keywords.casefold():
            continue
        items.append({
            "id": int(row.entry_id),
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


async def delete_memory_entry_mongo(entry_id: int, *, bot_id: int | None = None) -> bool:
    row = await LlmMemoryEntry.find_one({"entry_id": int(entry_id)})
    if row is None:
        return False
    if bot_id is not None and int(row.bot_id or 0) != int(bot_id):
        return False
    await row.delete()
    return True
