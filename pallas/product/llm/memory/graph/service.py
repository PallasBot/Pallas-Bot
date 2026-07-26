"""记忆图谱业务：Episode 投影、关系备注物化、统计与检索。"""

from __future__ import annotations

from typing import Any

from pallas.product.llm.memory.graph.scope import make_scope_key, resolve_scope
from pallas.product.llm.memory.graph.store import (
    is_memory_graph_store_available,
    list_categories,
    list_edges,
    list_entities,
    list_scopes,
    upsert_edge,
    upsert_entity,
)
from pallas.product.llm.memory.observation import observation_queue_size
from pallas.product.llm.memory.ops import list_memory_entity_summaries_async
from pallas.product.llm.memory.relationship_store import is_relationship_store_available
from pallas.product.llm.memory.store import is_llm_memory_store_available, list_memory_entries
from pallas.product.persona.prompt_guard import sanitize_prompt_literal


async def list_episodes(
    *,
    bot_id: int,
    group_id: int | None = None,
    query: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not is_llm_memory_store_available():
        return []
    entries = await list_memory_entries(bot_id, group_id, query=query, limit=limit)
    out: list[dict[str, Any]] = []
    for entry in entries:
        gid = int(entry.get("group_id") or 0)
        out.append({
            "id": str(int(entry.get("id") or 0)),
            "scope_key": make_scope_key(bot_id=bot_id, group_id=gid),
            "bot_id": int(bot_id),
            "group_id": gid,
            "content": str(entry.get("content") or ""),
            "keywords": str(entry.get("keywords") or ""),
            "source": str(entry.get("source") or "teach"),
            "speaker_ids": [],
            "created_at": int(entry.get("created_at") or 0),
            "updated_at": int(entry.get("updated_at") or 0),
            "valid_at": int(entry.get("updated_at") or entry.get("created_at") or 0),
        })
    return out


async def materialize_relationship_notes(
    *,
    bot_id: int,
    group_id: int | None = None,
) -> dict[str, int]:
    """把关系备注投影为 person 实体与边（幂等 upsert）。"""
    if not is_memory_graph_store_available() or not is_relationship_store_available():
        return {"entities": 0, "edges": 0}
    notes = await _fallback_list_relationship_notes(bot_id, group_id)

    bot_entity = await upsert_entity(
        bot_id=bot_id,
        group_id=group_id,
        name="牛牛",
        summary="当前 Bot",
        kind="bot",
        source="projected",
    )
    entity_n = 1 if bot_entity else 0
    edge_n = 0
    bot_entity_id = int(bot_entity["entity_id"]) if bot_entity else 0
    for note in notes:
        uid = int(note.get("user_id") or 0)
        content = str(note.get("content") or "").strip()
        note_gid = int(note.get("group_id") or 0)
        use_gid = group_id if group_id is not None else note_gid
        if uid <= 0 or not content or bot_entity_id <= 0:
            continue
        person = await upsert_entity(
            bot_id=bot_id,
            group_id=use_gid,
            name=f"用户{uid}",
            summary=content[:120],
            kind="person",
            user_id=uid,
            source="projected",
        )
        if not person:
            continue
        entity_n += 1
        edge = await upsert_edge(
            bot_id=bot_id,
            group_id=use_gid,
            fact=content,
            source_entity_id=bot_entity_id,
            target_entity_id=int(person["entity_id"]),
            relation_type="relationship",
            weight=float(note.get("weight") or 1.0),
            source="projected",
        )
        if edge:
            edge_n += 1
    return {"entities": entity_n, "edges": edge_n}


async def _fallback_list_relationship_notes(bot_id: int, group_id: int | None) -> list[dict[str, Any]]:
    from pallas.core.foundation.db.runtime import is_mongodb_backend, is_postgresql_backend

    if is_mongodb_backend():
        from pallas.core.foundation.db.modules import LlmRelationshipNote

        filt: dict[str, Any] = {"bot_id": int(bot_id)}
        if group_id is not None:
            from pallas.product.llm.session_models import normalize_group_scope

            filt["group_id"] = normalize_group_scope(group_id)
        docs = await LlmRelationshipNote.find(filt).limit(200).to_list()
        return [
            {
                "id": int(d.note_id),
                "bot_id": int(d.bot_id),
                "group_id": int(d.group_id),
                "user_id": int(d.user_id),
                "content": str(d.content or ""),
                "weight": float(d.weight or 1.0),
            }
            for d in docs
        ]
    if not is_postgresql_backend():
        return []
    from sqlalchemy import select

    from pallas.core.foundation.db.repository_pg import LlmRelationshipNoteRow, get_session
    from pallas.product.llm.session_models import normalize_group_scope

    async with get_session(read_only=True) as session:
        stmt = select(LlmRelationshipNoteRow).where(LlmRelationshipNoteRow.bot_id == int(bot_id))
        if group_id is not None:
            stmt = stmt.where(LlmRelationshipNoteRow.group_id == normalize_group_scope(group_id))
        rows = (await session.execute(stmt.limit(200))).scalars().all()
    return [
        {
            "id": int(r.id),
            "bot_id": int(r.bot_id),
            "group_id": int(r.group_id),
            "user_id": int(r.user_id),
            "content": str(r.content or ""),
            "weight": float(r.weight or 1.0),
        }
        for r in rows
    ]


async def materialize_keyword_entities(
    *,
    bot_id: int,
    group_id: int | None = None,
    limit: int = 40,
) -> int:
    summaries = await list_memory_entity_summaries_async(bot_id=bot_id, group_id=group_id, limit=limit)
    n = 0
    for item in summaries:
        name = sanitize_prompt_literal(str(item.get("name") or ""), max_len=32)
        if not name:
            continue
        ent = await upsert_entity(
            bot_id=bot_id,
            group_id=group_id,
            name=name,
            summary=f"提及 {int(item.get('mention_count') or 0)} 次",
            kind="concept",
            tags=[name],
            source="projected",
        )
        if ent:
            n += 1
    return n


async def build_graph_stats(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    materialize: bool = True,
) -> dict[str, Any]:
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    if materialize:
        await materialize_relationship_notes(bot_id=bid, group_id=gid or None)
        await materialize_keyword_entities(bot_id=bid, group_id=gid or None, limit=30)
    episodes = await list_episodes(bot_id=bid, group_id=gid or None, limit=200)
    entities = await list_entities(bot_id=bid, group_id=gid or None, limit=200)
    edges = await list_edges(bot_id=bid, group_id=gid or None, limit=500)
    categories = await list_categories(bot_id=bid, group_id=gid or None, limit=500)
    speaker_n = sum(1 for e in entities if e.get("kind") == "person")
    return {
        "scope_key": sk,
        "episode_count": len(episodes),
        "entity_count": len(entities),
        "speaker_entity_count": speaker_n,
        "edge_count": len(edges),
        "active_edge_count": sum(1 for e in edges if e.get("invalid_at") is None),
        "category_count": len(categories),
        "observation_queue_size": observation_queue_size(),
        "scope_keys": [s["scope_key"] for s in await list_scopes(bot_id=bid, limit=50)],
    }


async def build_graph_payload(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    materialize: bool = True,
    limit: int = 200,
) -> dict[str, Any]:
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    if materialize:
        await materialize_relationship_notes(bot_id=bid, group_id=gid or None)
        await materialize_keyword_entities(bot_id=bid, group_id=gid or None, limit=40)
    entities = await list_entities(bot_id=bid, group_id=gid or None, limit=limit)
    edges = await list_edges(bot_id=bid, group_id=gid or None, limit=limit)
    categories = await list_categories(bot_id=bid, group_id=gid or None, limit=limit)
    name_by_id = {str(e["id"]): str(e["name"]) for e in entities}
    nodes = [
        {
            "id": str(e["id"]),
            "label": str(e["name"]),
            "kind": str(e.get("kind") or "concept"),
            "summary": str(e.get("summary") or ""),
            "is_speaker": bool(e.get("is_speaker")),
        }
        for e in entities
    ]
    for cat in categories:
        cat_id = f"cat:{cat['category_id']}"
        nodes.append({
            "id": cat_id,
            "label": str(cat.get("name") or ""),
            "kind": "category",
            "summary": str(cat.get("summary") or ""),
            "is_speaker": False,
            "layer": int(cat.get("layer") or 1),
        })
        name_by_id[cat_id] = str(cat.get("name") or "")
    links = [
        {
            "id": str(edge["id"]),
            "source": str(edge["source_entity_id"]),
            "target": str(edge["target_entity_id"]),
            "fact": str(edge.get("fact") or ""),
            "weight": float(edge.get("weight") or 1.0),
            "source_name": name_by_id.get(str(edge["source_entity_id"]), ""),
            "target_name": name_by_id.get(str(edge["target_entity_id"]), ""),
        }
        for edge in edges
    ]
    for cat in categories:
        cat_id = f"cat:{cat['category_id']}"
        for mid in cat.get("member_entity_ids") or []:
            ent_id = str(mid).strip()
            if not ent_id:
                continue
            links.append({
                "id": f"catlink:{cat['category_id']}:{ent_id}",
                "source": ent_id,
                "target": cat_id,
                "fact": "member_of",
                "weight": 1.0,
                "source_name": name_by_id.get(ent_id, ""),
                "target_name": name_by_id.get(cat_id, ""),
            })
        parent_id = cat.get("parent_id")
        if parent_id is not None:
            parent_node = f"cat:{int(parent_id)}"
            links.append({
                "id": f"catlink:{cat['category_id']}:parent:{parent_id}",
                "source": cat_id,
                "target": parent_node,
                "fact": "child_of",
                "weight": 1.0,
                "source_name": name_by_id.get(cat_id, ""),
                "target_name": name_by_id.get(parent_node, ""),
            })
    return {
        "scope_key": sk,
        "nodes": nodes,
        "edges": links,
        "total_nodes": len(nodes),
        "total_edges": len(links),
    }


async def search_memory_graph(
    *,
    bot_id: int,
    group_id: int | None = None,
    query: str,
    limit: int = 30,
) -> dict[str, Any]:
    needle = str(query or "").strip()
    if not needle:
        return {"query": "", "episodes": [], "entities": [], "categories": [], "edges": [], "count": 0}
    max_limit = max(1, min(int(limit), 50))
    episodes = await list_episodes(bot_id=bot_id, group_id=group_id, query=needle, limit=max_limit)
    entities = await list_entities(bot_id=bot_id, group_id=group_id, query=needle, limit=max_limit)
    categories = await list_categories(bot_id=bot_id, group_id=group_id, query=needle, limit=max_limit)
    edges = await list_edges(bot_id=bot_id, group_id=group_id, limit=200)
    cf = needle.casefold()
    edge_hits = [e for e in edges if cf in str(e.get("fact") or "").casefold()][:max_limit]
    return {
        "query": needle,
        "episodes": episodes,
        "entities": entities,
        "categories": categories,
        "edges": edge_hits,
        "count": len(episodes) + len(entities) + len(categories) + len(edge_hits),
    }
