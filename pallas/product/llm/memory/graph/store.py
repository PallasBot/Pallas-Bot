"""记忆图谱：实体 / 边持久化（PG + Mongo 双后端）。"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import select

from pallas.core.foundation.db.repository_pg import (
    LlmMemoryCategoryRow,
    LlmMemoryEdgeRow,
    LlmMemoryEntityRow,
    LlmMemoryHierStatusRow,
    get_session,
)
from pallas.core.foundation.db.runtime import is_mongodb_backend, is_postgresql_backend
from pallas.product.llm.memory.graph.scope import make_scope_key, resolve_scope
from pallas.product.llm.session_backend import llm_product_storage_ready
from pallas.product.persona.prompt_guard import sanitize_prompt_literal


def is_memory_graph_store_available() -> bool:
    return llm_product_storage_ready()


def _use_mongodb_backend() -> bool:
    return is_mongodb_backend()


def _use_postgresql_backend() -> bool:
    return is_postgresql_backend()


def _tags_to_json(tags: list[str] | None) -> str:
    cleaned = [sanitize_prompt_literal(t, max_len=32) for t in (tags or [])]
    cleaned = [t for t in cleaned if t][:16]
    return json.dumps(cleaned, ensure_ascii=False)


def _tags_from_json(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()][:16]


def _episode_ids_to_json(ids: list[str] | None) -> str:
    cleaned = [str(x).strip() for x in (ids or []) if str(x).strip()][:32]
    return json.dumps(cleaned, ensure_ascii=False)


def _episode_ids_from_json(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()][:32]


def _entity_dict_from_row(row: LlmMemoryEntityRow) -> dict[str, Any]:
    return {
        "id": str(int(row.id)),
        "entity_id": int(row.id),
        "scope_key": str(row.scope_key),
        "bot_id": int(row.bot_id),
        "group_id": int(row.group_id),
        "name": str(row.name or ""),
        "summary": str(row.summary or ""),
        "tags": _tags_from_json(row.tags_json),
        "kind": str(row.kind or "concept"),
        "user_id": int(row.user_id) if row.user_id is not None else None,
        "is_speaker": str(row.kind or "") == "person",
        "source": str(row.source or "manual"),
        "deleted_at": int(row.deleted_at) if row.deleted_at is not None else None,
        "created_at": int(row.created_at or 0),
        "updated_at": int(row.updated_at or 0),
        "projected": False,
    }


def _member_ids_to_json(ids: list[str] | None) -> str:
    cleaned = [str(x).strip() for x in (ids or []) if str(x).strip()][:128]
    return json.dumps(cleaned, ensure_ascii=False)


def _member_ids_from_json(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()][:128]


def _category_dict_from_row(row: LlmMemoryCategoryRow) -> dict[str, Any]:
    return {
        "id": str(int(row.id)),
        "category_id": int(row.id),
        "scope_key": str(row.scope_key),
        "bot_id": int(row.bot_id),
        "group_id": int(row.group_id),
        "name": str(row.name or ""),
        "summary": str(row.summary or ""),
        "tags": _tags_from_json(row.tags_json),
        "layer": int(row.layer or 1),
        "parent_id": int(row.parent_id) if row.parent_id is not None else None,
        "member_entity_ids": _member_ids_from_json(row.member_entity_ids_json),
        "source": str(row.source or "manual"),
        "deleted_at": int(row.deleted_at) if row.deleted_at is not None else None,
        "created_at": int(row.created_at or 0),
        "updated_at": int(row.updated_at or 0),
    }


def _hier_status_dict_from_row(row: LlmMemoryHierStatusRow) -> dict[str, Any]:
    return {
        "scope_key": str(row.scope_key),
        "bot_id": int(row.bot_id),
        "group_id": int(row.group_id),
        "max_layer": int(row.max_layer or 0),
        "last_rebuild_at": int(row.last_rebuild_at or 0),
        "entity_count_at_rebuild": int(row.entity_count_at_rebuild or 0),
        "group_summary": str(row.group_summary or ""),
        "updated_at": int(row.updated_at or 0),
    }


def _edge_dict_from_row(row: LlmMemoryEdgeRow) -> dict[str, Any]:
    return {
        "id": str(int(row.id)),
        "edge_id": int(row.id),
        "scope_key": str(row.scope_key),
        "bot_id": int(row.bot_id),
        "group_id": int(row.group_id),
        "fact": str(row.fact or ""),
        "source_entity_id": str(int(row.source_entity_id)),
        "target_entity_id": str(int(row.target_entity_id)),
        "relation_type": str(row.relation_type or "related_to"),
        "weight": float(row.weight or 1.0),
        "mention_count": int(row.mention_count or 1),
        "episode_ids": _episode_ids_from_json(row.episode_ids_json),
        "valid_at": int(row.valid_at or 0),
        "invalid_at": int(row.invalid_at) if row.invalid_at is not None else None,
        "source": str(row.source or "manual"),
        "created_at": int(row.created_at or 0),
        "updated_at": int(row.updated_at or 0),
        "projected": False,
    }


async def upsert_entity(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    name: str,
    summary: str = "",
    tags: list[str] | None = None,
    kind: str = "concept",
    user_id: int | None = None,
    source: str = "manual",
) -> dict[str, Any] | None:
    if not is_memory_graph_store_available():
        return None
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    safe_name = sanitize_prompt_literal(name, max_len=64)
    if not safe_name:
        return None
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import upsert_entity_mongo

        return await upsert_entity_mongo(
            scope_key=sk,
            bot_id=bid,
            group_id=gid,
            name=safe_name,
            summary=summary,
            tags=tags,
            kind=kind,
            user_id=user_id,
            source=source,
        )
    if not _use_postgresql_backend():
        return None
    now = int(time.time())
    safe_summary = sanitize_prompt_literal(summary, max_len=500) or ""
    safe_kind = sanitize_prompt_literal(kind, max_len=32) or "concept"
    safe_source = sanitize_prompt_literal(source, max_len=16) or "manual"
    tags_json = _tags_to_json(tags)
    async with get_session() as session:
        existing = (
            await session.execute(
                select(LlmMemoryEntityRow).where(
                    LlmMemoryEntityRow.scope_key == sk,
                    LlmMemoryEntityRow.name == safe_name,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            row = LlmMemoryEntityRow(
                scope_key=sk,
                bot_id=bid,
                group_id=gid,
                name=safe_name,
                summary=safe_summary,
                tags_json=tags_json,
                kind=safe_kind,
                user_id=int(user_id) if user_id else None,
                source=safe_source,
                deleted_at=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return _entity_dict_from_row(row)
        existing.summary = safe_summary or str(existing.summary or "")
        existing.tags_json = tags_json if tags is not None else existing.tags_json
        existing.kind = safe_kind
        if user_id is not None:
            existing.user_id = int(user_id)
        existing.source = safe_source
        existing.deleted_at = None
        existing.updated_at = now
        await session.flush()
        return _entity_dict_from_row(existing)


async def list_entities(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    query: str = "",
    kind: str | None = None,
    limit: int = 50,
    include_deleted: bool = False,
    only_deleted: bool = False,
) -> list[dict[str, Any]]:
    if not is_memory_graph_store_available():
        return []
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import list_entities_mongo

        return await list_entities_mongo(
            scope_key=sk,
            bot_id=bid,
            group_id=gid,
            query=query,
            kind=kind,
            limit=limit,
            include_deleted=include_deleted,
            only_deleted=only_deleted,
        )
    if not _use_postgresql_backend():
        return []
    max_limit = max(1, min(int(limit), 200))
    async with get_session(read_only=True) as session:
        stmt = select(LlmMemoryEntityRow).where(LlmMemoryEntityRow.scope_key == sk)
        if only_deleted:
            stmt = stmt.where(LlmMemoryEntityRow.deleted_at.is_not(None))
        elif not include_deleted:
            stmt = stmt.where(LlmMemoryEntityRow.deleted_at.is_(None))
        if kind:
            stmt = stmt.where(LlmMemoryEntityRow.kind == str(kind))
        rows = (
            (
                await session.execute(
                    stmt.order_by(LlmMemoryEntityRow.updated_at.desc(), LlmMemoryEntityRow.id.desc()).limit(
                        max_limit * 3
                    )
                )
            )
            .scalars()
            .all()
        )
    needle = str(query or "").strip().casefold()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _entity_dict_from_row(row)
        if needle and needle not in item["name"].casefold() and needle not in item["summary"].casefold():
            continue
        out.append(item)
        if len(out) >= max_limit:
            break
    return out


async def get_entity(entity_id: int, *, bot_id: int | None = None) -> dict[str, Any] | None:
    if not is_memory_graph_store_available() or int(entity_id) <= 0:
        return None
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import get_entity_mongo

        return await get_entity_mongo(int(entity_id), bot_id=bot_id)
    if not _use_postgresql_backend():
        return None
    async with get_session(read_only=True) as session:
        row = (
            await session.execute(select(LlmMemoryEntityRow).where(LlmMemoryEntityRow.id == int(entity_id)))
        ).scalar_one_or_none()
        if row is None:
            return None
        if bot_id is not None and int(row.bot_id) != int(bot_id):
            return None
        return _entity_dict_from_row(row)


async def delete_entity(entity_id: int, *, bot_id: int | None = None) -> bool:
    """软删实体：设 deleted_at，并软删关联边。"""
    if not is_memory_graph_store_available() or int(entity_id) <= 0:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import delete_entity_mongo

        return await delete_entity_mongo(int(entity_id), bot_id=bot_id)
    if not _use_postgresql_backend():
        return False
    async with get_session() as session:
        row = (
            await session.execute(select(LlmMemoryEntityRow).where(LlmMemoryEntityRow.id == int(entity_id)))
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id) != int(bot_id):
            return False
        now = int(time.time())
        if row.deleted_at is None:
            row.deleted_at = now
            row.updated_at = now
        edges = (
            (
                await session.execute(
                    select(LlmMemoryEdgeRow).where(
                        (LlmMemoryEdgeRow.source_entity_id == int(entity_id))
                        | (LlmMemoryEdgeRow.target_entity_id == int(entity_id))
                    )
                )
            )
            .scalars()
            .all()
        )
        for edge in edges:
            if edge.invalid_at is None:
                edge.invalid_at = now
                edge.updated_at = now
        await session.flush()
        return True


async def restore_entity(entity_id: int, *, bot_id: int | None = None) -> bool:
    if not is_memory_graph_store_available() or int(entity_id) <= 0:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import restore_entity_mongo

        return await restore_entity_mongo(int(entity_id), bot_id=bot_id)
    if not _use_postgresql_backend():
        return False
    async with get_session() as session:
        row = (
            await session.execute(select(LlmMemoryEntityRow).where(LlmMemoryEntityRow.id == int(entity_id)))
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id) != int(bot_id):
            return False
        if row.deleted_at is None:
            return True
        row.deleted_at = None
        row.updated_at = int(time.time())
        await session.flush()
        return True


async def purge_entity(entity_id: int, *, bot_id: int | None = None) -> bool:
    """硬删除实体及其关联边。"""
    if not is_memory_graph_store_available() or int(entity_id) <= 0:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import purge_entity_mongo

        return await purge_entity_mongo(int(entity_id), bot_id=bot_id)
    if not _use_postgresql_backend():
        return False
    async with get_session() as session:
        row = (
            await session.execute(select(LlmMemoryEntityRow).where(LlmMemoryEntityRow.id == int(entity_id)))
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id) != int(bot_id):
            return False
        edges = (
            (
                await session.execute(
                    select(LlmMemoryEdgeRow).where(
                        (LlmMemoryEdgeRow.source_entity_id == int(entity_id))
                        | (LlmMemoryEdgeRow.target_entity_id == int(entity_id))
                    )
                )
            )
            .scalars()
            .all()
        )
        for edge in edges:
            await session.delete(edge)
        await session.delete(row)
        await session.flush()
        return True


async def upsert_edge(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    fact: str,
    source_entity_id: int,
    target_entity_id: int,
    relation_type: str = "related_to",
    weight: float = 1.0,
    episode_ids: list[str] | None = None,
    source: str = "manual",
) -> dict[str, Any] | None:
    if not is_memory_graph_store_available():
        return None
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    safe_fact = sanitize_prompt_literal(fact, max_len=500)
    if not safe_fact or int(source_entity_id) <= 0 or int(target_entity_id) <= 0:
        return None
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import upsert_edge_mongo

        return await upsert_edge_mongo(
            scope_key=sk,
            bot_id=bid,
            group_id=gid,
            fact=safe_fact,
            source_entity_id=int(source_entity_id),
            target_entity_id=int(target_entity_id),
            relation_type=relation_type,
            weight=weight,
            episode_ids=episode_ids,
            source=source,
        )
    if not _use_postgresql_backend():
        return None
    now = int(time.time())
    safe_rel = sanitize_prompt_literal(relation_type, max_len=32) or "related_to"
    safe_source = sanitize_prompt_literal(source, max_len=16) or "manual"
    async with get_session() as session:
        existing = (
            await session.execute(
                select(LlmMemoryEdgeRow).where(
                    LlmMemoryEdgeRow.scope_key == sk,
                    LlmMemoryEdgeRow.source_entity_id == int(source_entity_id),
                    LlmMemoryEdgeRow.target_entity_id == int(target_entity_id),
                    LlmMemoryEdgeRow.fact == safe_fact,
                    LlmMemoryEdgeRow.invalid_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            row = LlmMemoryEdgeRow(
                scope_key=sk,
                bot_id=bid,
                group_id=gid,
                fact=safe_fact,
                source_entity_id=int(source_entity_id),
                target_entity_id=int(target_entity_id),
                relation_type=safe_rel,
                weight=float(weight),
                mention_count=1,
                episode_ids_json=_episode_ids_to_json(episode_ids),
                valid_at=now,
                invalid_at=None,
                source=safe_source,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return _edge_dict_from_row(row)
        existing.weight = max(float(existing.weight or 1.0), float(weight))
        existing.mention_count = int(existing.mention_count or 1) + 1
        existing.relation_type = safe_rel
        existing.source = safe_source
        if episode_ids is not None:
            existing.episode_ids_json = _episode_ids_to_json(episode_ids)
        existing.updated_at = now
        await session.flush()
        return _edge_dict_from_row(existing)


async def list_edges(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    include_invalid: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not is_memory_graph_store_available():
        return []
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import list_edges_mongo

        return await list_edges_mongo(
            scope_key=sk, bot_id=bid, group_id=gid, include_invalid=include_invalid, limit=limit
        )
    if not _use_postgresql_backend():
        return []
    max_limit = max(1, min(int(limit), 500))
    async with get_session(read_only=True) as session:
        stmt = select(LlmMemoryEdgeRow).where(LlmMemoryEdgeRow.scope_key == sk)
        if not include_invalid:
            stmt = stmt.where(LlmMemoryEdgeRow.invalid_at.is_(None))
        rows = (
            (
                await session.execute(
                    stmt.order_by(LlmMemoryEdgeRow.updated_at.desc(), LlmMemoryEdgeRow.id.desc()).limit(max_limit)
                )
            )
            .scalars()
            .all()
        )
    return [_edge_dict_from_row(row) for row in rows]


async def soft_delete_edge(edge_id: int, *, bot_id: int | None = None) -> bool:
    if not is_memory_graph_store_available() or int(edge_id) <= 0:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import soft_delete_edge_mongo

        return await soft_delete_edge_mongo(int(edge_id), bot_id=bot_id)
    if not _use_postgresql_backend():
        return False
    async with get_session() as session:
        row = (
            await session.execute(select(LlmMemoryEdgeRow).where(LlmMemoryEdgeRow.id == int(edge_id)))
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id) != int(bot_id):
            return False
        row.invalid_at = int(time.time())
        row.updated_at = int(time.time())
        await session.flush()
        return True


async def restore_edge(edge_id: int, *, bot_id: int | None = None) -> bool:
    """清除 invalid_at，恢复软删关系。"""
    if not is_memory_graph_store_available() or int(edge_id) <= 0:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import restore_edge_mongo

        return await restore_edge_mongo(int(edge_id), bot_id=bot_id)
    if not _use_postgresql_backend():
        return False
    async with get_session() as session:
        row = (
            await session.execute(select(LlmMemoryEdgeRow).where(LlmMemoryEdgeRow.id == int(edge_id)))
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id) != int(bot_id):
            return False
        if row.invalid_at is None:
            return True
        row.invalid_at = None
        row.updated_at = int(time.time())
        await session.flush()
        return True


async def upsert_category(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    name: str,
    summary: str = "",
    tags: list[str] | None = None,
    layer: int = 1,
    parent_id: int | None = None,
    member_entity_ids: list[str] | None = None,
    source: str = "manual",
) -> dict[str, Any] | None:
    if not is_memory_graph_store_available():
        return None
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    safe_name = sanitize_prompt_literal(name, max_len=64)
    if not safe_name:
        return None
    safe_layer = max(1, min(int(layer or 1), 16))
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import upsert_category_mongo

        return await upsert_category_mongo(
            scope_key=sk,
            bot_id=bid,
            group_id=gid,
            name=safe_name,
            summary=summary,
            tags=tags,
            layer=safe_layer,
            parent_id=parent_id,
            member_entity_ids=member_entity_ids,
            source=source,
        )
    if not _use_postgresql_backend():
        return None
    now = int(time.time())
    safe_summary = sanitize_prompt_literal(summary, max_len=500) or ""
    safe_source = sanitize_prompt_literal(source, max_len=16) or "manual"
    tags_json = _tags_to_json(tags)
    members_json = _member_ids_to_json(member_entity_ids)
    async with get_session() as session:
        existing = (
            await session.execute(
                select(LlmMemoryCategoryRow).where(
                    LlmMemoryCategoryRow.scope_key == sk,
                    LlmMemoryCategoryRow.layer == safe_layer,
                    LlmMemoryCategoryRow.name == safe_name,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            row = LlmMemoryCategoryRow(
                scope_key=sk,
                bot_id=bid,
                group_id=gid,
                name=safe_name,
                summary=safe_summary,
                tags_json=tags_json,
                layer=safe_layer,
                parent_id=int(parent_id) if parent_id else None,
                member_entity_ids_json=members_json,
                source=safe_source,
                deleted_at=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return _category_dict_from_row(row)
        existing.summary = safe_summary or str(existing.summary or "")
        if tags is not None:
            existing.tags_json = tags_json
        if member_entity_ids is not None:
            existing.member_entity_ids_json = members_json
        existing.parent_id = int(parent_id) if parent_id else None
        existing.source = safe_source
        existing.deleted_at = None
        existing.updated_at = now
        await session.flush()
        return _category_dict_from_row(existing)


async def list_categories(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    layer: int | None = None,
    query: str = "",
    limit: int = 100,
    include_deleted: bool = False,
    only_deleted: bool = False,
) -> list[dict[str, Any]]:
    if not is_memory_graph_store_available():
        return []
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import list_categories_mongo

        return await list_categories_mongo(
            scope_key=sk,
            bot_id=bid,
            group_id=gid,
            layer=layer,
            query=query,
            limit=limit,
            include_deleted=include_deleted,
            only_deleted=only_deleted,
        )
    if not _use_postgresql_backend():
        return []
    max_limit = max(1, min(int(limit), 500))
    async with get_session(read_only=True) as session:
        stmt = select(LlmMemoryCategoryRow).where(LlmMemoryCategoryRow.scope_key == sk)
        if only_deleted:
            stmt = stmt.where(LlmMemoryCategoryRow.deleted_at.is_not(None))
        elif not include_deleted:
            stmt = stmt.where(LlmMemoryCategoryRow.deleted_at.is_(None))
        if layer is not None:
            stmt = stmt.where(LlmMemoryCategoryRow.layer == int(layer))
        rows = (
            (
                await session.execute(
                    stmt.order_by(
                        LlmMemoryCategoryRow.layer.asc(),
                        LlmMemoryCategoryRow.updated_at.desc(),
                        LlmMemoryCategoryRow.id.desc(),
                    ).limit(max_limit * 2)
                )
            )
            .scalars()
            .all()
        )
    needle = str(query or "").strip().casefold()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _category_dict_from_row(row)
        if needle and needle not in item["name"].casefold() and needle not in item["summary"].casefold():
            continue
        out.append(item)
        if len(out) >= max_limit:
            break
    return out


async def soft_delete_category(category_id: int, *, bot_id: int | None = None) -> bool:
    if not is_memory_graph_store_available() or int(category_id) <= 0:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import soft_delete_category_mongo

        return await soft_delete_category_mongo(int(category_id), bot_id=bot_id)
    if not _use_postgresql_backend():
        return False
    async with get_session() as session:
        row = (
            await session.execute(select(LlmMemoryCategoryRow).where(LlmMemoryCategoryRow.id == int(category_id)))
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id) != int(bot_id):
            return False
        if row.deleted_at is None:
            now = int(time.time())
            row.deleted_at = now
            row.updated_at = now
            await session.flush()
        return True


async def restore_category(category_id: int, *, bot_id: int | None = None) -> bool:
    if not is_memory_graph_store_available() or int(category_id) <= 0:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import restore_category_mongo

        return await restore_category_mongo(int(category_id), bot_id=bot_id)
    if not _use_postgresql_backend():
        return False
    async with get_session() as session:
        row = (
            await session.execute(select(LlmMemoryCategoryRow).where(LlmMemoryCategoryRow.id == int(category_id)))
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id) != int(bot_id):
            return False
        if row.deleted_at is None:
            return True
        row.deleted_at = None
        row.updated_at = int(time.time())
        await session.flush()
        return True


async def purge_category(category_id: int, *, bot_id: int | None = None) -> bool:
    if not is_memory_graph_store_available() or int(category_id) <= 0:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import purge_category_mongo

        return await purge_category_mongo(int(category_id), bot_id=bot_id)
    if not _use_postgresql_backend():
        return False
    async with get_session() as session:
        row = (
            await session.execute(select(LlmMemoryCategoryRow).where(LlmMemoryCategoryRow.id == int(category_id)))
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id) != int(bot_id):
            return False
        await session.delete(row)
        await session.flush()
        return True


async def get_hier_status(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
) -> dict[str, Any] | None:
    if not is_memory_graph_store_available():
        return None
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import get_hier_status_mongo

        return await get_hier_status_mongo(scope_key=sk, bot_id=bid, group_id=gid)
    if not _use_postgresql_backend():
        return None
    async with get_session(read_only=True) as session:
        row = (
            await session.execute(select(LlmMemoryHierStatusRow).where(LlmMemoryHierStatusRow.scope_key == sk))
        ).scalar_one_or_none()
        if row is None:
            return None
        return _hier_status_dict_from_row(row)


async def set_hier_status(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    max_layer: int = 0,
    last_rebuild_at: int | None = None,
    entity_count_at_rebuild: int = 0,
    group_summary: str = "",
) -> dict[str, Any] | None:
    if not is_memory_graph_store_available():
        return None
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    now = int(time.time())
    rebuild_at = int(last_rebuild_at) if last_rebuild_at is not None else now
    safe_summary = sanitize_prompt_literal(group_summary, max_len=1000) or ""
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import set_hier_status_mongo

        return await set_hier_status_mongo(
            scope_key=sk,
            bot_id=bid,
            group_id=gid,
            max_layer=max_layer,
            last_rebuild_at=rebuild_at,
            entity_count_at_rebuild=entity_count_at_rebuild,
            group_summary=safe_summary,
        )
    if not _use_postgresql_backend():
        return None
    async with get_session() as session:
        row = (
            await session.execute(select(LlmMemoryHierStatusRow).where(LlmMemoryHierStatusRow.scope_key == sk))
        ).scalar_one_or_none()
        if row is None:
            row = LlmMemoryHierStatusRow(
                scope_key=sk,
                bot_id=bid,
                group_id=gid,
                max_layer=int(max_layer),
                last_rebuild_at=rebuild_at,
                entity_count_at_rebuild=int(entity_count_at_rebuild),
                group_summary=safe_summary,
                updated_at=now,
            )
            session.add(row)
        else:
            row.bot_id = bid
            row.group_id = gid
            row.max_layer = int(max_layer)
            row.last_rebuild_at = rebuild_at
            row.entity_count_at_rebuild = int(entity_count_at_rebuild)
            row.group_summary = safe_summary
            row.updated_at = now
        await session.flush()
        return _hier_status_dict_from_row(row)


async def list_trash(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """回收站：已删实体、失效边、已删类目。"""
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    max_limit = max(1, min(int(limit), 200))
    entities = await list_entities(bot_id=bid, group_id=gid, scope_key=sk, only_deleted=True, limit=max_limit)
    categories = await list_categories(bot_id=bid, group_id=gid, scope_key=sk, only_deleted=True, limit=max_limit)
    edges = await list_edges(bot_id=bid, group_id=gid, scope_key=sk, include_invalid=True, limit=max_limit * 2)
    invalid_edges = [e for e in edges if e.get("invalid_at") is not None][:max_limit]
    return {
        "scope_key": sk,
        "entities": entities,
        "edges": invalid_edges,
        "categories": categories,
        "count": len(entities) + len(invalid_edges) + len(categories),
    }


async def clear_scope_graph(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    hard: bool = False,
) -> dict[str, int]:
    """清空 scope 图谱：默认软删；hard=True 时硬删。"""
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    if not is_memory_graph_store_available():
        return {"entities": 0, "edges": 0, "categories": 0}
    if _use_mongodb_backend():
        from pallas.product.llm.memory.graph.store_mongo import clear_scope_graph_mongo

        return await clear_scope_graph_mongo(scope_key=sk, bot_id=bid, group_id=gid, hard=hard)
    if not _use_postgresql_backend():
        return {"entities": 0, "edges": 0, "categories": 0}

    now = int(time.time())
    ent_n = 0
    edge_n = 0
    cat_n = 0
    async with get_session() as session:
        entities = (
            (await session.execute(select(LlmMemoryEntityRow).where(LlmMemoryEntityRow.scope_key == sk)))
            .scalars()
            .all()
        )
        edges = (
            (await session.execute(select(LlmMemoryEdgeRow).where(LlmMemoryEdgeRow.scope_key == sk))).scalars().all()
        )
        cats = (
            (await session.execute(select(LlmMemoryCategoryRow).where(LlmMemoryCategoryRow.scope_key == sk)))
            .scalars()
            .all()
        )
        if hard:
            for row in edges:
                await session.delete(row)
                edge_n += 1
            for row in entities:
                await session.delete(row)
                ent_n += 1
            for row in cats:
                await session.delete(row)
                cat_n += 1
            status = (
                await session.execute(select(LlmMemoryHierStatusRow).where(LlmMemoryHierStatusRow.scope_key == sk))
            ).scalar_one_or_none()
            if status is not None:
                await session.delete(status)
        else:
            for row in entities:
                if row.deleted_at is None:
                    row.deleted_at = now
                    row.updated_at = now
                    ent_n += 1
            for row in edges:
                if row.invalid_at is None:
                    row.invalid_at = now
                    row.updated_at = now
                    edge_n += 1
            for row in cats:
                if row.deleted_at is None:
                    row.deleted_at = now
                    row.updated_at = now
                    cat_n += 1
        await session.flush()
    return {"entities": ent_n, "edges": edge_n, "categories": cat_n}


async def list_scopes(*, bot_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """从实体/边与记忆条目汇总 scope 列表。"""
    from pallas.product.llm.memory.store import list_memory_entries

    if not is_memory_graph_store_available():
        return []
    max_limit = max(1, min(int(limit), 200))
    buckets: dict[str, dict[str, Any]] = {}

    def touch(sk: str, *, episode: int = 0, entity: int = 0, edge: int = 0) -> None:
        item = buckets.setdefault(
            sk,
            {
                "scope_key": sk,
                "bot_id": 0,
                "group_id": 0,
                "episode_count": 0,
                "entity_count": 0,
                "edge_count": 0,
            },
        )
        from pallas.product.llm.memory.graph.scope import parse_scope_key

        b, g = parse_scope_key(sk)
        if b:
            item["bot_id"] = b
        if g is not None:
            item["group_id"] = g
        item["episode_count"] += episode
        item["entity_count"] += entity
        item["edge_count"] += edge

    if bot_id and int(bot_id) > 0:
        entries = await list_memory_entries(int(bot_id), None, limit=200)
        for entry in entries:
            sk = make_scope_key(bot_id=int(bot_id), group_id=int(entry.get("group_id") or 0))
            touch(sk, episode=1)
        entities = await list_entities(bot_id=int(bot_id), group_id=None, limit=200)
        # list_entities requires resolve with group - when group_id None it uses group 0.
        # Better list all entities for bot via raw query.
        if _use_postgresql_backend():
            async with get_session(read_only=True) as session:
                rows = (
                    (
                        await session.execute(
                            select(LlmMemoryEntityRow)
                            .where(
                                LlmMemoryEntityRow.bot_id == int(bot_id),
                                LlmMemoryEntityRow.deleted_at.is_(None),
                            )
                            .limit(500)
                        )
                    )
                    .scalars()
                    .all()
                )
                edge_rows = (
                    (
                        await session.execute(
                            select(LlmMemoryEdgeRow)
                            .where(
                                LlmMemoryEdgeRow.bot_id == int(bot_id),
                                LlmMemoryEdgeRow.invalid_at.is_(None),
                            )
                            .limit(500)
                        )
                    )
                    .scalars()
                    .all()
                )
            for row in rows:
                touch(str(row.scope_key), entity=1)
            for row in edge_rows:
                touch(str(row.scope_key), edge=1)
        else:
            for ent in entities:
                touch(str(ent.get("scope_key") or ""), entity=1)

    ranked = sorted(
        buckets.values(),
        key=lambda x: (-(x["episode_count"] + x["entity_count"] + x["edge_count"]), x["scope_key"]),
    )
    return ranked[:max_limit]
