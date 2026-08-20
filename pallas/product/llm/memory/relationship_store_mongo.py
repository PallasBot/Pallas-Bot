from __future__ import annotations

import time

from beanie import SortDirection
from nonebot import logger
from pymongo.errors import DuplicateKeyError

from pallas.core.foundation.db.modules import LlmRelationshipNote
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.relationship import (
    clamp_affinity,
    clamp_user_relationship_delta,
    merge_relationship_facts,
    normalize_relationship_note,
    prefer_relationship_source,
)
from pallas.product.llm.memory.relationship_store import RelationshipProfile, decayed_weight
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


def _delta_limit(cfg: LlmConfig) -> float:
    return float(getattr(cfg, "llm_relationship_affect_delta_max", 0.15) or 0.15)


def _affinity_limit(cfg: LlmConfig) -> float:
    return float(getattr(cfg, "llm_relationship_affinity_delta_max", 0.15) or 0.15)


async def upsert_relationship_profile_mongo(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    *,
    content: str | None = None,
    source: str = "auto",
    warmth_delta_add: float = 0.0,
    assertiveness_delta_add: float = 0.0,
    affinity_delta_add: float = 0.0,
    merge_content: bool = True,
    cfg: LlmConfig | None = None,
) -> bool:
    if not user_id:
        return False
    c = cfg or get_llm_config()
    incoming = normalize_relationship_note(content or "", max_len=c.llm_relationship_content_max_len)
    has_fact = bool(incoming)
    has_delta = warmth_delta_add != 0.0 or assertiveness_delta_add != 0.0 or affinity_delta_add != 0.0
    if not has_fact and not has_delta:
        return False
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    safe_source = sanitize_prompt_literal(source, max_len=16) or "auto"
    limit = _delta_limit(c)
    existing = await LlmRelationshipNote.find_one({
        "bot_id": int(bot_id),
        "group_id": scope_gid,
        "user_id": int(user_id),
    })
    if existing is not None:
        if has_fact:
            if merge_content:
                existing.content = merge_relationship_facts(
                    str(existing.content or ""),
                    incoming,
                    max_len=c.llm_relationship_content_max_len,
                )
            else:
                existing.content = incoming
        existing.source = prefer_relationship_source(str(existing.source or ""), safe_source)
        existing.warmth_delta = clamp_user_relationship_delta(
            float(getattr(existing, "warmth_delta", 0.0) or 0.0) + float(warmth_delta_add),
            limit=limit,
        )
        existing.assertiveness_delta = clamp_user_relationship_delta(
            float(getattr(existing, "assertiveness_delta", 0.0) or 0.0) + float(assertiveness_delta_add),
            limit=limit,
        )
        existing.affinity = clamp_affinity(
            float(getattr(existing, "affinity", 0.0) or 0.0) + float(affinity_delta_add)
        )
        existing.weight = 1.0
        existing.updated_at = now
        await existing.save()
        return True
    for _ in range(_RELATIONSHIP_ID_INSERT_RETRIES):
        try:
            await LlmRelationshipNote(
                note_id=await next_relationship_note_id(),
                bot_id=int(bot_id),
                group_id=scope_gid,
                user_id=int(user_id),
                content=incoming if has_fact else "",
                source=safe_source,
                weight=1.0,
                warmth_delta=clamp_user_relationship_delta(float(warmth_delta_add), limit=limit),
                assertiveness_delta=clamp_user_relationship_delta(
                    float(assertiveness_delta_add),
                    limit=limit,
                ),
                affinity=clamp_affinity(float(affinity_delta_add)),
                created_at=now,
                updated_at=now,
            ).insert()
            return True
        except DuplicateKeyError:
            continue
    logger.warning("llm relationship note insert failed after duplicate note_id retries")
    return False


async def save_relationship_note_mongo(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    content: str,
    *,
    source: str = "teach",
    cfg: LlmConfig | None = None,
) -> bool:
    return await upsert_relationship_profile_mongo(
        bot_id,
        group_id,
        user_id,
        content=content,
        source=source,
        merge_content=True,
        cfg=cfg,
    )


async def retrieve_relationship_profile_mongo(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    *,
    cfg: LlmConfig | None = None,
) -> RelationshipProfile | None:
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
    warmth = clamp_user_relationship_delta(
        float(getattr(row, "warmth_delta", 0.0) or 0.0),
        limit=_delta_limit(c),
    )
    assertiveness = clamp_user_relationship_delta(
        float(getattr(row, "assertiveness_delta", 0.0) or 0.0),
        limit=_delta_limit(c),
    )
    affinity = clamp_affinity(float(getattr(row, "affinity", 0.0) or 0.0))
    if not content and warmth == 0.0 and assertiveness == 0.0 and affinity == 0.0:
        return None
    return RelationshipProfile(
        content=content,
        warmth_delta=warmth,
        assertiveness_delta=assertiveness,
        affinity=affinity,
        source=str(row.source or "").strip() or "auto",
        weight=weight,
    )


async def retrieve_relationship_note_mongo(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    *,
    cfg: LlmConfig | None = None,
) -> str | None:
    profile = await retrieve_relationship_profile_mongo(bot_id, group_id, user_id, cfg=cfg)
    if profile is None or not profile.has_facts:
        return None
    return profile.content


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
            "warmth_delta": float(getattr(row, "warmth_delta", 0.0) or 0.0),
            "assertiveness_delta": float(getattr(row, "assertiveness_delta", 0.0) or 0.0),
            "affinity": float(getattr(row, "affinity", 0.0) or 0.0),
            "created_at": int(row.created_at or 0),
            "updated_at": int(row.updated_at or 0),
        })
        if len(items) >= max_limit:
            break
    return items


async def set_affinity_mongo(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    affinity: float,
    *,
    cfg: LlmConfig | None = None,
) -> bool:
    if not user_id:
        return False
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    value = clamp_affinity(float(affinity))
    existing = await LlmRelationshipNote.find_one({
        "bot_id": int(bot_id),
        "group_id": scope_gid,
        "user_id": int(user_id),
    })
    if existing is not None:
        existing.affinity = value
        existing.updated_at = now
        await existing.save()
        return True
    for _ in range(_RELATIONSHIP_ID_INSERT_RETRIES):
        try:
            await LlmRelationshipNote(
                note_id=await next_relationship_note_id(),
                bot_id=int(bot_id),
                group_id=scope_gid,
                user_id=int(user_id),
                content="",
                source="auto",
                weight=1.0,
                affinity=value,
                created_at=now,
                updated_at=now,
            ).insert()
            return True
        except DuplicateKeyError:
            continue
    logger.warning("llm relationship affinity set failed after duplicate note_id retries")
    return False


async def delete_relationship_note_mongo(note_id: int, *, bot_id: int | None = None) -> bool:
    row = await LlmRelationshipNote.find_one({"note_id": int(note_id)})
    if row is None:
        return False
    if bot_id is not None and int(row.bot_id or 0) != int(bot_id):
        return False
    await row.delete()
    return True
