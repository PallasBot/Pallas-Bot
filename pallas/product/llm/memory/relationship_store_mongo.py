from __future__ import annotations

import time

from beanie import SortDirection
from nonebot import logger
from pymongo.errors import DuplicateKeyError

from pallas.core.foundation.db.modules import LlmRelationshipNote
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.relationship import normalize_relationship_note
from pallas.product.llm.memory.relationship_store import decayed_weight
from pallas.product.llm.mongo_id import allocate_mongo_int_id
from pallas.product.llm.session_models import normalize_group_scope
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

_RELATIONSHIP_ID_INSERT_RETRIES = 8


async def _peek_max_relationship_note_id() -> int:
    rows = await LlmRelationshipNote.find_all().sort([("note_id", SortDirection.DESCENDING)]).limit(1).to_list()
    if not rows:
        return 0
    return int(rows[0].note_id or 0)


async def next_relationship_note_id() -> int:
    return await allocate_mongo_int_id("llm_relationship_note", peek_max=_peek_max_relationship_note_id)


async def save_relationship_note_mongo(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    content: str,
    *,
    source: str = "teach",
    cfg: LlmConfig | None = None,
) -> bool:
    if not user_id:
        return False
    c = cfg or get_llm_config()
    safe_content = normalize_relationship_note(content, max_len=c.llm_relationship_content_max_len)
    if not safe_content:
        return False
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    safe_source = sanitize_prompt_literal(source, max_len=16) or "teach"
    existing = await LlmRelationshipNote.find_one({
        "bot_id": int(bot_id),
        "group_id": scope_gid,
        "user_id": int(user_id),
    })
    if existing is not None:
        existing.content = safe_content
        existing.source = safe_source
        existing.weight = 1.0
        existing.updated_at = now
        await existing.save()
    else:
        for _ in range(_RELATIONSHIP_ID_INSERT_RETRIES):
            try:
                await LlmRelationshipNote(
                    note_id=await next_relationship_note_id(),
                    bot_id=int(bot_id),
                    group_id=scope_gid,
                    user_id=int(user_id),
                    content=safe_content,
                    source=safe_source,
                    weight=1.0,
                    created_at=now,
                    updated_at=now,
                ).insert()
                return True
            except DuplicateKeyError:
                continue
        logger.warning("llm relationship note insert failed after duplicate note_id retries")
        return False
    return True


async def retrieve_relationship_note_mongo(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    *,
    cfg: LlmConfig | None = None,
) -> str | None:
    if not user_id:
        return None
    c = cfg or get_llm_config()
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    row = await LlmRelationshipNote.find_one({
        "bot_id": int(bot_id),
        "group_id": scope_gid,
        "user_id": int(user_id),
    })
    if row is None:
        return None
    weight = decayed_weight(
        float(row.weight or 0.0),
        int(row.updated_at or 0),
        half_life_days=c.llm_relationship_half_life_days,
        now=now,
    )
    if weight < c.llm_relationship_min_weight:
        return None
    content = str(row.content or "").strip()
    return content or None


async def trim_relationship_notes_mongo(
    bot_id: int,
    group_id: int | None,
    *,
    cfg: LlmConfig | None = None,
) -> int:
    c = cfg or get_llm_config()
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    rows = await LlmRelationshipNote.find({
        "bot_id": int(bot_id),
        "group_id": scope_gid,
    }).to_list()
    deleted = 0
    for row in rows:
        weight = decayed_weight(
            float(row.weight or 0.0),
            int(row.updated_at or 0),
            half_life_days=c.llm_relationship_half_life_days,
            now=now,
        )
        if weight < c.llm_relationship_min_weight:
            await row.delete()
            deleted += 1
    return deleted


async def list_relationship_notes_mongo(
    bot_id: int,
    group_id: int | None,
    *,
    query: str = "",
    limit: int = 50,
) -> list[dict[str, object]]:
    max_limit = max(1, min(int(limit), 200))
    filt: dict = {"bot_id": int(bot_id)}
    if group_id is not None:
        filt["group_id"] = normalize_group_scope(group_id)
    rows = (
        await LlmRelationshipNote
        .find(filt)
        .sort([("updated_at", SortDirection.DESCENDING), ("note_id", SortDirection.DESCENDING)])
        .limit(max_limit * 4)
        .to_list()
    )
    needle = str(query or "").strip().casefold()
    items: list[dict[str, object]] = []
    for row in rows:
        content = str(row.content or "").strip()
        source = str(row.source or "").strip() or "teach"
        if needle and needle not in content.casefold() and needle not in source.casefold():
            continue
        items.append({
            "id": int(row.note_id),
            "bot_id": int(row.bot_id),
            "group_id": int(row.group_id),
            "user_id": int(row.user_id),
            "content": content,
            "source": source,
            "weight": float(row.weight or 0.0),
            "created_at": int(row.created_at or 0),
            "updated_at": int(row.updated_at or 0),
        })
        if len(items) >= max_limit:
            break
    return items


async def delete_relationship_note_mongo(note_id: int, *, bot_id: int | None = None) -> bool:
    row = await LlmRelationshipNote.find_one({"note_id": int(note_id)})
    if row is None:
        return False
    if bot_id is not None and int(row.bot_id or 0) != int(bot_id):
        return False
    await row.delete()
    return True
