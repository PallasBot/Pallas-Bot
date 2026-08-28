"""记忆图谱 Mongo 后端。"""

from __future__ import annotations

import time
from typing import Any

from pymongo import SortDirection

from pallas.core.foundation.db.modules import LlmMemoryCategory, LlmMemoryEdge, LlmMemoryEntity, LlmMemoryHierStatus
from pallas.product.llm.mongo_id import allocate_mongo_int_id
from pallas.product.persona.prompt_guard import sanitize_prompt_literal


async def _peek_max_entity_id() -> int:
    rows = await LlmMemoryEntity.find_all().sort([("entity_id", SortDirection.DESCENDING)]).limit(1).to_list()
    return int(rows[0].entity_id) if rows else 0


async def _peek_max_edge_id() -> int:
    rows = await LlmMemoryEdge.find_all().sort([("edge_id", SortDirection.DESCENDING)]).limit(1).to_list()
    return int(rows[0].edge_id) if rows else 0


async def _peek_max_category_id() -> int:
    rows = await LlmMemoryCategory.find_all().sort([("category_id", SortDirection.DESCENDING)]).limit(1).to_list()
    return int(rows[0].category_id) if rows else 0


async def next_entity_id() -> int:
    return await allocate_mongo_int_id("llm_memory_entity", peek_max=_peek_max_entity_id)


async def next_edge_id() -> int:
    return await allocate_mongo_int_id("llm_memory_edge", peek_max=_peek_max_edge_id)


async def next_category_id() -> int:
    return await allocate_mongo_int_id("llm_memory_category", peek_max=_peek_max_category_id)


def _entity_dict(doc: LlmMemoryEntity) -> dict[str, Any]:
    return {
        "id": str(int(doc.entity_id)),
        "entity_id": int(doc.entity_id),
        "scope_key": str(doc.scope_key),
        "bot_id": int(doc.bot_id),
        "group_id": int(doc.group_id),
        "name": str(doc.name or ""),
        "summary": str(doc.summary or ""),
        "tags": list(doc.tags or [])[:16],
        "kind": str(doc.kind or "concept"),
        "user_id": int(doc.user_id) if doc.user_id is not None else None,
        "is_speaker": str(doc.kind or "") == "person",
        "source": str(doc.source or "manual"),
        "deleted_at": int(doc.deleted_at) if doc.deleted_at is not None else None,
        "created_at": int(doc.created_at or 0),
        "updated_at": int(doc.updated_at or 0),
        "projected": False,
    }


def _edge_dict(doc: LlmMemoryEdge) -> dict[str, Any]:
    return {
        "id": str(int(doc.edge_id)),
        "edge_id": int(doc.edge_id),
        "scope_key": str(doc.scope_key),
        "bot_id": int(doc.bot_id),
        "group_id": int(doc.group_id),
        "fact": str(doc.fact or ""),
        "source_entity_id": str(int(doc.source_entity_id)),
        "target_entity_id": str(int(doc.target_entity_id)),
        "relation_type": str(doc.relation_type or "related_to"),
        "weight": float(doc.weight or 1.0),
        "mention_count": int(doc.mention_count or 1),
        "episode_ids": [str(x) for x in (doc.episode_ids or [])][:32],
        "valid_at": int(doc.valid_at or 0),
        "invalid_at": int(doc.invalid_at) if doc.invalid_at is not None else None,
        "source": str(doc.source or "manual"),
        "created_at": int(doc.created_at or 0),
        "updated_at": int(doc.updated_at or 0),
        "projected": False,
    }


def _category_dict(doc: LlmMemoryCategory) -> dict[str, Any]:
    return {
        "id": str(int(doc.category_id)),
        "category_id": int(doc.category_id),
        "scope_key": str(doc.scope_key),
        "bot_id": int(doc.bot_id),
        "group_id": int(doc.group_id),
        "name": str(doc.name or ""),
        "summary": str(doc.summary or ""),
        "tags": list(doc.tags or [])[:16],
        "layer": int(doc.layer or 1),
        "parent_id": int(doc.parent_id) if doc.parent_id is not None else None,
        "member_entity_ids": [str(x) for x in (doc.member_entity_ids or [])][:128],
        "source": str(doc.source or "manual"),
        "deleted_at": int(doc.deleted_at) if doc.deleted_at is not None else None,
        "created_at": int(doc.created_at or 0),
        "updated_at": int(doc.updated_at or 0),
    }


def _hier_status_dict(doc: LlmMemoryHierStatus) -> dict[str, Any]:
    return {
        "scope_key": str(doc.scope_key),
        "bot_id": int(doc.bot_id),
        "group_id": int(doc.group_id),
        "max_layer": int(doc.max_layer or 0),
        "last_rebuild_at": int(doc.last_rebuild_at or 0),
        "entity_count_at_rebuild": int(doc.entity_count_at_rebuild or 0),
        "group_summary": str(doc.group_summary or ""),
        "updated_at": int(doc.updated_at or 0),
    }


async def upsert_entity_mongo(
    *,
    scope_key: str,
    bot_id: int,
    group_id: int,
    name: str,
    summary: str = "",
    tags: list[str] | None = None,
    kind: str = "concept",
    user_id: int | None = None,
    source: str = "manual",
) -> dict[str, Any] | None:
    now = int(time.time())
    safe_summary = sanitize_prompt_literal(summary, max_len=500) or ""
    safe_kind = sanitize_prompt_literal(kind, max_len=32) or "concept"
    safe_source = sanitize_prompt_literal(source, max_len=16) or "manual"
    cleaned_tags = [sanitize_prompt_literal(t, max_len=32) for t in (tags or [])]
    cleaned_tags = [t for t in cleaned_tags if t][:16]
    existing = await LlmMemoryEntity.find_one({"scope_key": scope_key, "name": name})
    if existing is None:
        doc = LlmMemoryEntity(
            entity_id=await next_entity_id(),
            scope_key=scope_key,
            bot_id=bot_id,
            group_id=group_id,
            name=name,
            summary=safe_summary,
            tags=cleaned_tags,
            kind=safe_kind,
            user_id=int(user_id) if user_id else None,
            source=safe_source,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
        await doc.insert()
        return _entity_dict(doc)
    existing.summary = safe_summary or str(existing.summary or "")
    if tags is not None:
        existing.tags = cleaned_tags
    existing.kind = safe_kind
    if user_id is not None:
        existing.user_id = int(user_id)
    existing.source = safe_source
    existing.deleted_at = None
    existing.updated_at = now
    await existing.save()
    return _entity_dict(existing)


async def list_entities_mongo(
    *,
    scope_key: str,
    bot_id: int,
    group_id: int,
    query: str = "",
    kind: str | None = None,
    limit: int = 50,
    include_deleted: bool = False,
    only_deleted: bool = False,
) -> list[dict[str, Any]]:
    del bot_id, group_id
    max_limit = max(1, min(int(limit), 200))
    filt: dict[str, Any] = {"scope_key": scope_key}
    if only_deleted:
        filt["deleted_at"] = {"$ne": None}
    elif not include_deleted:
        filt["deleted_at"] = None
    if kind:
        filt["kind"] = str(kind)
    docs = (
        await LlmMemoryEntity
        .find(filt)
        .sort([("updated_at", SortDirection.DESCENDING), ("entity_id", SortDirection.DESCENDING)])
        .limit(max_limit * 3)
        .to_list()
    )
    needle = str(query or "").strip().casefold()
    out: list[dict[str, Any]] = []
    for doc in docs:
        item = _entity_dict(doc)
        if needle and needle not in item["name"].casefold() and needle not in item["summary"].casefold():
            continue
        out.append(item)
        if len(out) >= max_limit:
            break
    return out


async def get_entity_mongo(entity_id: int, *, bot_id: int | None = None) -> dict[str, Any] | None:
    doc = await LlmMemoryEntity.find_one({"entity_id": int(entity_id)})
    if doc is None:
        return None
    if bot_id is not None and int(doc.bot_id) != int(bot_id):
        return None
    return _entity_dict(doc)


async def delete_entity_mongo(entity_id: int, *, bot_id: int | None = None) -> bool:
    doc = await LlmMemoryEntity.find_one({"entity_id": int(entity_id)})
    if doc is None:
        return False
    if bot_id is not None and int(doc.bot_id) != int(bot_id):
        return False
    now = int(time.time())
    if doc.deleted_at is None:
        doc.deleted_at = now
        doc.updated_at = now
        await doc.save()
    edges = await LlmMemoryEdge.find({
        "$or": [
            {"source_entity_id": int(entity_id)},
            {"target_entity_id": int(entity_id)},
        ]
    }).to_list()
    for edge in edges:
        if edge.invalid_at is None:
            edge.invalid_at = now
            edge.updated_at = now
            await edge.save()
    return True


async def restore_entity_mongo(entity_id: int, *, bot_id: int | None = None) -> bool:
    doc = await LlmMemoryEntity.find_one({"entity_id": int(entity_id)})
    if doc is None:
        return False
    if bot_id is not None and int(doc.bot_id) != int(bot_id):
        return False
    if doc.deleted_at is None:
        return True
    doc.deleted_at = None
    doc.updated_at = int(time.time())
    await doc.save()
    return True


async def purge_entity_mongo(entity_id: int, *, bot_id: int | None = None) -> bool:
    doc = await LlmMemoryEntity.find_one({"entity_id": int(entity_id)})
    if doc is None:
        return False
    if bot_id is not None and int(doc.bot_id) != int(bot_id):
        return False
    edges = await LlmMemoryEdge.find({
        "$or": [
            {"source_entity_id": int(entity_id)},
            {"target_entity_id": int(entity_id)},
        ]
    }).to_list()
    for edge in edges:
        await edge.delete()
    await doc.delete()
    return True


async def upsert_edge_mongo(
    *,
    scope_key: str,
    bot_id: int,
    group_id: int,
    fact: str,
    source_entity_id: int,
    target_entity_id: int,
    relation_type: str = "related_to",
    weight: float = 1.0,
    episode_ids: list[str] | None = None,
    source: str = "manual",
) -> dict[str, Any] | None:
    now = int(time.time())
    safe_rel = sanitize_prompt_literal(relation_type, max_len=32) or "related_to"
    safe_source = sanitize_prompt_literal(source, max_len=16) or "manual"
    existing = await LlmMemoryEdge.find_one({
        "scope_key": scope_key,
        "source_entity_id": int(source_entity_id),
        "target_entity_id": int(target_entity_id),
        "fact": fact,
        "invalid_at": None,
    })
    if existing is None:
        doc = LlmMemoryEdge(
            edge_id=await next_edge_id(),
            scope_key=scope_key,
            bot_id=bot_id,
            group_id=group_id,
            fact=fact,
            source_entity_id=int(source_entity_id),
            target_entity_id=int(target_entity_id),
            relation_type=safe_rel,
            weight=float(weight),
            mention_count=1,
            episode_ids=[str(x) for x in (episode_ids or []) if str(x).strip()][:32],
            valid_at=now,
            invalid_at=None,
            source=safe_source,
            created_at=now,
            updated_at=now,
        )
        await doc.insert()
        return _edge_dict(doc)
    existing.weight = max(float(existing.weight or 1.0), float(weight))
    existing.mention_count = int(existing.mention_count or 1) + 1
    existing.relation_type = safe_rel
    existing.source = safe_source
    if episode_ids is not None:
        existing.episode_ids = [str(x) for x in episode_ids if str(x).strip()][:32]
    existing.updated_at = now
    await existing.save()
    return _edge_dict(existing)


async def list_edges_mongo(
    *,
    scope_key: str,
    bot_id: int,
    group_id: int,
    include_invalid: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    del bot_id, group_id
    max_limit = max(1, min(int(limit), 500))
    filt: dict[str, Any] = {"scope_key": scope_key}
    if not include_invalid:
        filt["invalid_at"] = None
    docs = (
        await LlmMemoryEdge
        .find(filt)
        .sort([("updated_at", SortDirection.DESCENDING), ("edge_id", SortDirection.DESCENDING)])
        .limit(max_limit)
        .to_list()
    )
    return [_edge_dict(doc) for doc in docs]


async def soft_delete_edge_mongo(edge_id: int, *, bot_id: int | None = None) -> bool:
    doc = await LlmMemoryEdge.find_one({"edge_id": int(edge_id)})
    if doc is None:
        return False
    if bot_id is not None and int(doc.bot_id) != int(bot_id):
        return False
    now = int(time.time())
    doc.invalid_at = now
    doc.updated_at = now
    await doc.save()
    return True


async def restore_edge_mongo(edge_id: int, *, bot_id: int | None = None) -> bool:
    doc = await LlmMemoryEdge.find_one({"edge_id": int(edge_id)})
    if doc is None:
        return False
    if bot_id is not None and int(doc.bot_id) != int(bot_id):
        return False
    if doc.invalid_at is None:
        return True
    doc.invalid_at = None
    doc.updated_at = int(time.time())
    await doc.save()
    return True


async def upsert_category_mongo(
    *,
    scope_key: str,
    bot_id: int,
    group_id: int,
    name: str,
    summary: str = "",
    tags: list[str] | None = None,
    layer: int = 1,
    parent_id: int | None = None,
    member_entity_ids: list[str] | None = None,
    source: str = "manual",
) -> dict[str, Any] | None:
    now = int(time.time())
    safe_summary = sanitize_prompt_literal(summary, max_len=500) or ""
    safe_source = sanitize_prompt_literal(source, max_len=16) or "manual"
    cleaned_tags = [sanitize_prompt_literal(t, max_len=32) for t in (tags or [])]
    cleaned_tags = [t for t in cleaned_tags if t][:16]
    members = [str(x).strip() for x in (member_entity_ids or []) if str(x).strip()][:128]
    existing = await LlmMemoryCategory.find_one({"scope_key": scope_key, "layer": int(layer), "name": name})
    if existing is None:
        doc = LlmMemoryCategory(
            category_id=await next_category_id(),
            scope_key=scope_key,
            bot_id=bot_id,
            group_id=group_id,
            name=name,
            summary=safe_summary,
            tags=cleaned_tags,
            layer=int(layer),
            parent_id=int(parent_id) if parent_id else None,
            member_entity_ids=members,
            source=safe_source,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
        await doc.insert()
        return _category_dict(doc)
    existing.summary = safe_summary or str(existing.summary or "")
    if tags is not None:
        existing.tags = cleaned_tags
    if member_entity_ids is not None:
        existing.member_entity_ids = members
    existing.parent_id = int(parent_id) if parent_id else None
    existing.source = safe_source
    existing.deleted_at = None
    existing.updated_at = now
    await existing.save()
    return _category_dict(existing)


async def list_categories_mongo(
    *,
    scope_key: str,
    bot_id: int,
    group_id: int,
    layer: int | None = None,
    query: str = "",
    limit: int = 100,
    include_deleted: bool = False,
    only_deleted: bool = False,
) -> list[dict[str, Any]]:
    del bot_id, group_id
    max_limit = max(1, min(int(limit), 500))
    filt: dict[str, Any] = {"scope_key": scope_key}
    if only_deleted:
        filt["deleted_at"] = {"$ne": None}
    elif not include_deleted:
        filt["deleted_at"] = None
    if layer is not None:
        filt["layer"] = int(layer)
    docs = (
        await LlmMemoryCategory
        .find(filt)
        .sort([
            ("layer", SortDirection.ASCENDING),
            ("updated_at", SortDirection.DESCENDING),
            ("category_id", SortDirection.DESCENDING),
        ])
        .limit(max_limit * 2)
        .to_list()
    )
    needle = str(query or "").strip().casefold()
    out: list[dict[str, Any]] = []
    for doc in docs:
        item = _category_dict(doc)
        if needle and needle not in item["name"].casefold() and needle not in item["summary"].casefold():
            continue
        out.append(item)
        if len(out) >= max_limit:
            break
    return out


async def soft_delete_category_mongo(category_id: int, *, bot_id: int | None = None) -> bool:
    doc = await LlmMemoryCategory.find_one({"category_id": int(category_id)})
    if doc is None:
        return False
    if bot_id is not None and int(doc.bot_id) != int(bot_id):
        return False
    if doc.deleted_at is None:
        now = int(time.time())
        doc.deleted_at = now
        doc.updated_at = now
        await doc.save()
    return True


async def restore_category_mongo(category_id: int, *, bot_id: int | None = None) -> bool:
    doc = await LlmMemoryCategory.find_one({"category_id": int(category_id)})
    if doc is None:
        return False
    if bot_id is not None and int(doc.bot_id) != int(bot_id):
        return False
    if doc.deleted_at is None:
        return True
    doc.deleted_at = None
    doc.updated_at = int(time.time())
    await doc.save()
    return True


async def purge_category_mongo(category_id: int, *, bot_id: int | None = None) -> bool:
    doc = await LlmMemoryCategory.find_one({"category_id": int(category_id)})
    if doc is None:
        return False
    if bot_id is not None and int(doc.bot_id) != int(bot_id):
        return False
    await doc.delete()
    return True


async def get_hier_status_mongo(*, scope_key: str, bot_id: int, group_id: int) -> dict[str, Any] | None:
    del bot_id, group_id
    doc = await LlmMemoryHierStatus.find_one({"scope_key": scope_key})
    if doc is None:
        return None
    return _hier_status_dict(doc)


async def set_hier_status_mongo(
    *,
    scope_key: str,
    bot_id: int,
    group_id: int,
    max_layer: int = 0,
    last_rebuild_at: int = 0,
    entity_count_at_rebuild: int = 0,
    group_summary: str = "",
) -> dict[str, Any] | None:
    now = int(time.time())
    doc = await LlmMemoryHierStatus.find_one({"scope_key": scope_key})
    if doc is None:
        doc = LlmMemoryHierStatus(
            scope_key=scope_key,
            bot_id=bot_id,
            group_id=group_id,
            max_layer=int(max_layer),
            last_rebuild_at=int(last_rebuild_at),
            entity_count_at_rebuild=int(entity_count_at_rebuild),
            group_summary=group_summary,
            updated_at=now,
        )
        await doc.insert()
        return _hier_status_dict(doc)
    doc.bot_id = bot_id
    doc.group_id = group_id
    doc.max_layer = int(max_layer)
    doc.last_rebuild_at = int(last_rebuild_at)
    doc.entity_count_at_rebuild = int(entity_count_at_rebuild)
    doc.group_summary = group_summary
    doc.updated_at = now
    await doc.save()
    return _hier_status_dict(doc)


async def clear_scope_graph_mongo(
    *,
    scope_key: str,
    bot_id: int,
    group_id: int,
    hard: bool = False,
) -> dict[str, int]:
    del bot_id, group_id
    now = int(time.time())
    ent_n = 0
    edge_n = 0
    cat_n = 0
    entities = await LlmMemoryEntity.find({"scope_key": scope_key}).to_list()
    edges = await LlmMemoryEdge.find({"scope_key": scope_key}).to_list()
    cats = await LlmMemoryCategory.find({"scope_key": scope_key}).to_list()
    if hard:
        for row in edges:
            await row.delete()
            edge_n += 1
        for row in entities:
            await row.delete()
            ent_n += 1
        for row in cats:
            await row.delete()
            cat_n += 1
        status = await LlmMemoryHierStatus.find_one({"scope_key": scope_key})
        if status is not None:
            await status.delete()
    else:
        for row in entities:
            if row.deleted_at is None:
                row.deleted_at = now
                row.updated_at = now
                await row.save()
                ent_n += 1
        for row in edges:
            if row.invalid_at is None:
                row.invalid_at = now
                row.updated_at = now
                await row.save()
                edge_n += 1
        for row in cats:
            if row.deleted_at is None:
                row.deleted_at = now
                row.updated_at = now
                await row.save()
                cat_n += 1
    return {"entities": ent_n, "edges": edge_n, "categories": cat_n}
