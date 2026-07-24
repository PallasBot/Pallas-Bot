"""记忆图谱分层语义树（HierGraph）：LLM 主导分类与重建。"""

from __future__ import annotations

import time
from typing import Any

from nonebot import logger

from pallas.product.llm.config import get_llm_config
from pallas.product.llm.memory.graph.json_parse import parse_llm_json
from pallas.product.llm.memory.graph.scope import resolve_scope
from pallas.product.llm.memory.graph.store import (
    get_hier_status,
    is_memory_graph_store_available,
    list_categories,
    list_entities,
    set_hier_status,
    soft_delete_category,
    upsert_category,
)
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

_LAYER1_SYSTEM = """你是记忆图谱分层助手。将编号实体归入若干类目，只输出 JSON。

输出格式：
{"cats":[{"n":"类目名","s":"摘要","t":["标签"],"idx":[1,3]}]}

规则：
1. idx 为输入实体的 1-based 编号，每个实体至少出现一次。
2. 同类合并，类目名简短；发言者类可用 n="发言者"。
3. 不要臆造输入中没有的实体。
"""

_UPPER_SYSTEM = """你是记忆图谱高层分类助手。将编号的下层类目再归入更抽象的父类，只输出 JSON。

输出格式：
{"cats":[{"n":"父类名","s":"摘要","t":["标签"],"idx":[1,2]}]}

规则：idx 为输入类目的 1-based 编号；尽量减少父类数量；不要遗漏。
"""

_SUMMARY_SYSTEM = """根据类目名称，用一两句中文概括该群记忆主题。只输出纯文本，不要 JSON。"""


def _resolve_task_and_model() -> tuple[str, str]:
    from pallas.product.llm.providers_store import resolve_endpoint_for_task

    cfg = get_llm_config()
    for task in ("memory_extract", "llm_chat"):
        endpoint = resolve_endpoint_for_task(task)
        if endpoint is not None and endpoint.model:
            return task, endpoint.model
    return "llm_chat", str(cfg.llm_model or "").strip()


async def _chat(system: str, user: str) -> str:
    from pallas.product.llm.provider_client import complete_chat_message

    task, model = _resolve_task_and_model()
    if not model:
        raise RuntimeError("no llm model for hiergraph")
    message = await complete_chat_message(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=model,
        options={"temperature": 0.2, "num_predict": 1500},
        task=task,
    )
    return str(message.get("content") or "").strip()


def _parse_cat_assignments(raw: str, *, item_count: int) -> list[dict[str, Any]]:
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("hiergraph json not object")
    cats = data.get("cats") if isinstance(data.get("cats"), list) else data.get("categories")
    if not isinstance(cats, list):
        raise ValueError("missing cats")
    out: list[dict[str, Any]] = []
    for item in cats:
        if not isinstance(item, dict):
            continue
        name = sanitize_prompt_literal(str(item.get("n") or item.get("category") or ""), max_len=64)
        if not name:
            continue
        summary = sanitize_prompt_literal(str(item.get("s") or item.get("summary") or ""), max_len=200) or ""
        tags_raw = item.get("t") if isinstance(item.get("t"), list) else item.get("tags")
        tags = [sanitize_prompt_literal(str(t), max_len=32) for t in (tags_raw or [])]
        tags = [t for t in tags if t][:8]
        indexes_raw = item.get("idx") if item.get("idx") is not None else item.get("indexes")
        indexes: list[int] = []
        if isinstance(indexes_raw, list):
            for v in indexes_raw:
                try:
                    i = int(v)
                except (TypeError, ValueError):
                    continue
                if 1 <= i <= item_count:
                    indexes.append(i)
        if not indexes:
            continue
        out.append({"name": name, "summary": summary, "tags": tags, "indexes": indexes})
    return out


def _fallback_singleton_assignments(names: list[str]) -> list[dict[str, Any]]:
    return [
        {"name": name, "summary": f"关于{name}", "tags": [], "indexes": [i]}
        for i, name in enumerate(names, start=1)
        if name
    ]


async def _llm_assign(names: list[str], *, layer: int) -> list[dict[str, Any]]:
    if not names:
        return []
    lines = "\n".join(f"{i}. {n}" for i, n in enumerate(names, start=1))
    system = _LAYER1_SYSTEM if layer == 1 else _UPPER_SYSTEM
    user = f"layer={layer}\n节点列表：\n{lines}\n请输出 JSON。"
    try:
        raw = await _chat(system, user)
        return _parse_cat_assignments(raw, item_count=len(names))
    except Exception as exc:  # noqa: BLE001
        logger.warning("hiergraph llm assign failed layer={} err={}", layer, exc)
        return _fallback_singleton_assignments(names)


async def _maybe_group_summary(category_names: list[str]) -> str:
    if not category_names:
        return ""
    preview = "、".join(category_names[:40])
    try:
        text = await _chat(_SUMMARY_SYSTEM, f"类目：{preview}")
        return sanitize_prompt_literal(text, max_len=500) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("hiergraph group_summary failed err={}", exc)
        return ""


async def rebuild_hiergraph(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
    max_layers: int | None = None,
) -> dict[str, Any]:
    """全量重建分层图：软删旧类目后按层 LLM 分类写入。"""
    if not is_memory_graph_store_available():
        return {"ok": False, "error": "store unavailable"}
    sk, bid, gid = resolve_scope(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
    cfg = get_llm_config()
    layers = int(max_layers if max_layers is not None else cfg.llm_memory_hiergraph_max_layers)
    layers = max(1, min(layers, 6))

    old_cats = await list_categories(bot_id=bid, group_id=gid, scope_key=sk, include_deleted=False, limit=500)
    for cat in old_cats:
        await soft_delete_category(int(cat["category_id"]), bot_id=bid)

    entities = await list_entities(bot_id=bid, group_id=gid, scope_key=sk, limit=200)
    if not entities:
        now = int(time.time())
        await set_hier_status(
            bot_id=bid,
            group_id=gid,
            scope_key=sk,
            max_layer=0,
            last_rebuild_at=now,
            entity_count_at_rebuild=0,
            group_summary="",
        )
        return {"ok": True, "scope_key": sk, "max_layer": 0, "categories": 0, "entity_count": 0}

    # Layer 1：对实体编号分类
    entity_names = [str(e.get("name") or "") for e in entities]
    assignments = await _llm_assign(entity_names, layer=1)
    layer1: list[dict[str, Any]] = []
    for asg in assignments:
        member_ids: list[str] = []
        for idx in asg["indexes"]:
            ent = entities[idx - 1]
            member_ids.append(str(ent.get("id") or ent.get("entity_id") or ""))
        member_ids = [m for m in member_ids if m]
        cat = await upsert_category(
            bot_id=bid,
            group_id=gid,
            scope_key=sk,
            name=asg["name"],
            summary=asg["summary"],
            tags=asg["tags"],
            layer=1,
            parent_id=None,
            member_entity_ids=member_ids,
            source="hiergraph",
        )
        if cat:
            layer1.append(cat)

    prev = layer1
    max_layer = 1 if prev else 0
    for layer in range(2, layers + 1):
        if len(prev) < 2:
            break
        child_names = [str(c.get("name") or "") for c in prev]
        upper = await _llm_assign(child_names, layer=layer)
        if not upper:
            break
        # 节点数不减则停止（避免无意义膨胀）
        if len(upper) >= len(prev):
            break
        new_layer: list[dict[str, Any]] = []
        for asg in upper:
            parent = await upsert_category(
                bot_id=bid,
                group_id=gid,
                scope_key=sk,
                name=asg["name"],
                summary=asg["summary"],
                tags=asg["tags"],
                layer=layer,
                parent_id=None,
                member_entity_ids=[],
                source="hiergraph",
            )
            if not parent:
                continue
            parent_id = int(parent["category_id"])
            for idx in asg["indexes"]:
                child = prev[idx - 1]
                await upsert_category(
                    bot_id=bid,
                    group_id=gid,
                    scope_key=sk,
                    name=str(child.get("name") or ""),
                    summary=str(child.get("summary") or ""),
                    tags=list(child.get("tags") or []),
                    layer=int(child.get("layer") or layer - 1),
                    parent_id=parent_id,
                    member_entity_ids=list(child.get("member_entity_ids") or []),
                    source=str(child.get("source") or "hiergraph"),
                )
            new_layer.append(parent)
        if not new_layer:
            break
        prev = new_layer
        max_layer = layer

    top_names = [str(c.get("name") or "") for c in prev]
    group_summary = await _maybe_group_summary(top_names)
    now = int(time.time())
    await set_hier_status(
        bot_id=bid,
        group_id=gid,
        scope_key=sk,
        max_layer=max_layer,
        last_rebuild_at=now,
        entity_count_at_rebuild=len(entities),
        group_summary=group_summary,
    )
    all_cats = await list_categories(bot_id=bid, group_id=gid, scope_key=sk, limit=500)
    return {
        "ok": True,
        "scope_key": sk,
        "max_layer": max_layer,
        "categories": len(all_cats),
        "entity_count": len(entities),
        "group_summary": group_summary,
    }


async def get_hiergraph_status(
    *,
    bot_id: int,
    group_id: int | None = None,
    scope_key: str | None = None,
) -> dict[str, Any] | None:
    return await get_hier_status(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
