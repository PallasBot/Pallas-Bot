"""记忆图谱 scope 级导入导出。"""

from __future__ import annotations

from typing import Any

from pallas.product.llm.memory.graph.scope import resolve_scope
from pallas.product.llm.memory.graph.service import list_episodes
from pallas.product.llm.memory.graph.store import (
    is_memory_graph_store_available,
    list_categories,
    list_edges,
    list_entities,
    upsert_category,
    upsert_edge,
    upsert_entity,
)
from pallas.product.persona.prompt_guard import sanitize_prompt_literal


async def export_scope_graph(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
) -> dict[str, Any]:
    """导出 scope 内 episodes / entities / edges / categories。"""
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    if not is_memory_graph_store_available():
        return {
            "scope_key": sk,
            "bot_id": bid,
            "group_id": gid,
            "episodes": [],
            "entities": [],
            "edges": [],
            "categories": [],
        }
    episodes = await list_episodes(bot_id=bid, group_id=gid or None, limit=200)
    entities = await list_entities(bot_id=bid, group_id=gid, scope_key=sk, limit=200)
    edges = await list_edges(bot_id=bid, group_id=gid, scope_key=sk, include_invalid=False, limit=500)
    categories = await list_categories(bot_id=bid, group_id=gid, scope_key=sk, limit=500)
    return {
        "scope_key": sk,
        "bot_id": bid,
        "group_id": gid,
        "episodes": episodes,
        "entities": entities,
        "edges": edges,
        "categories": categories,
    }


async def import_scope_graph(
    *,
    bot_id: int,
    group_id: int | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """将 payload 写入当前 bot/group scope；边可用实体名或 id 解析。"""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload must be object"}
    if not is_memory_graph_store_available():
        return {"ok": False, "error": "store unavailable"}
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id)

    entities_in = payload.get("entities") if isinstance(payload.get("entities"), list) else []
    edges_in = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    cats_in = payload.get("categories") if isinstance(payload.get("categories"), list) else []

    name_to_id: dict[str, int] = {}
    id_remap: dict[str, int] = {}
    entities_n = 0
    for item in entities_in:
        if not isinstance(item, dict):
            continue
        name = sanitize_prompt_literal(str(item.get("name") or ""), max_len=64)
        if not name:
            continue
        ent = await upsert_entity(
            bot_id=bid,
            group_id=gid,
            scope_key=sk,
            name=name,
            summary=str(item.get("summary") or ""),
            tags=item.get("tags") if isinstance(item.get("tags"), list) else None,
            kind=str(item.get("kind") or "concept"),
            user_id=int(item["user_id"]) if item.get("user_id") is not None else None,
            source=str(item.get("source") or "import"),
        )
        if not ent:
            continue
        entities_n += 1
        eid = int(ent["entity_id"])
        name_to_id[name] = eid
        name_to_id[name.casefold()] = eid
        old_id = str(item.get("id") or item.get("entity_id") or "").strip()
        if old_id:
            id_remap[old_id] = eid

    def resolve_entity_ref(ref: Any) -> int:
        if ref is None:
            return 0
        text = str(ref).strip()
        if not text:
            return 0
        if text in id_remap:
            return id_remap[text]
        if text in name_to_id:
            return name_to_id[text]
        if text.casefold() in name_to_id:
            return name_to_id[text.casefold()]
        try:
            as_int = int(text)
        except ValueError:
            return 0
        # 已是本库 id
        return max(0, as_int)

    edges_n = 0
    for item in edges_in:
        if not isinstance(item, dict):
            continue
        fact = sanitize_prompt_literal(str(item.get("fact") or ""), max_len=500)
        if not fact:
            continue
        src = resolve_entity_ref(item.get("source_entity_id") or item.get("src") or item.get("source_name"))
        tgt = resolve_entity_ref(item.get("target_entity_id") or item.get("tgt") or item.get("target_name"))
        if src <= 0 or tgt <= 0:
            # 尝试按名称字段
            src_name = sanitize_prompt_literal(str(item.get("source_name") or item.get("src") or ""), max_len=64)
            tgt_name = sanitize_prompt_literal(str(item.get("target_name") or item.get("tgt") or ""), max_len=64)
            if src <= 0 and src_name:
                src = name_to_id.get(src_name) or name_to_id.get(src_name.casefold()) or 0
            if tgt <= 0 and tgt_name:
                tgt = name_to_id.get(tgt_name) or name_to_id.get(tgt_name.casefold()) or 0
        if src <= 0 or tgt <= 0:
            continue
        edge = await upsert_edge(
            bot_id=bid,
            group_id=gid,
            scope_key=sk,
            fact=fact,
            source_entity_id=src,
            target_entity_id=tgt,
            relation_type=str(item.get("relation_type") or "related_to"),
            weight=float(item.get("weight") or 1.0),
            episode_ids=item.get("episode_ids") if isinstance(item.get("episode_ids"), list) else None,
            source=str(item.get("source") or "import"),
        )
        if edge:
            edges_n += 1

    # 先写无 parent，再回填 parent（按层升序）
    cats_sorted = sorted(
        [c for c in cats_in if isinstance(c, dict)],
        key=lambda c: int(c.get("layer") or 1),
    )
    cat_id_remap: dict[str, int] = {}
    cats_n = 0
    for item in cats_sorted:
        name = sanitize_prompt_literal(str(item.get("name") or ""), max_len=64)
        if not name:
            continue
        parent_ref = item.get("parent_id")
        parent_id = None
        if parent_ref is not None and str(parent_ref).strip():
            mapped = cat_id_remap.get(str(parent_ref).strip())
            if mapped:
                parent_id = mapped
            else:
                try:
                    parent_id = int(parent_ref)
                except (TypeError, ValueError):
                    parent_id = None
        members = item.get("member_entity_ids") if isinstance(item.get("member_entity_ids"), list) else []
        remapped_members: list[str] = []
        for mid in members:
            key = str(mid).strip()
            if key in id_remap:
                remapped_members.append(str(id_remap[key]))
            else:
                remapped_members.append(key)
        cat = await upsert_category(
            bot_id=bid,
            group_id=gid,
            scope_key=sk,
            name=name,
            summary=str(item.get("summary") or ""),
            tags=item.get("tags") if isinstance(item.get("tags"), list) else None,
            layer=int(item.get("layer") or 1),
            parent_id=parent_id,
            member_entity_ids=remapped_members,
            source=str(item.get("source") or "import"),
        )
        if cat:
            cats_n += 1
            old = str(item.get("id") or item.get("category_id") or "").strip()
            if old:
                cat_id_remap[old] = int(cat["category_id"])

    return {
        "ok": True,
        "scope_key": sk,
        "entities_upserted": entities_n,
        "edges_upserted": edges_n,
        "categories_upserted": cats_n,
    }
