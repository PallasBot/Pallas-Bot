"""记忆运维：统计、清空、检索预览、生命周期与偏好。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from nonebot import logger
from sqlalchemy import delete, func, select

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.inject import enrich_system_with_memory_context
from pallas.product.llm.memory.store import (
    is_llm_memory_store_available,
    list_memory_entries,
    retrieve_memory_hits,
)
from pallas.product.llm.session_models import normalize_group_scope
from pallas.product.persona.prompt_guard import sanitize_prompt_block, sanitize_prompt_literal

LifecycleAction = Literal["reinforce", "weaken", "freeze", "unfreeze", "forget"]

_PREF_POLARITIES = frozenset({"do", "dont", "neutral"})


def _data_dir() -> Path:
    from pallas.core.foundation.paths import plugin_data_dir

    env_dir = str(__import__("os").environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir) / "pallas_llm"
    else:
        root = plugin_data_dir("pb_webui", create=True) / "pallas_llm"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _lifecycle_path() -> Path:
    return _data_dir() / "memory_lifecycle.json"


def _preferences_path() -> Path:
    return _data_dir() / "memory_preferences.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("llm ops json read failed path={} err={}", path, exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _lifecycle_state() -> dict[str, Any]:
    return _read_json(_lifecycle_path())


def _save_lifecycle_state(state: dict[str, Any]) -> None:
    _write_json(_lifecycle_path(), state)


def memory_lifecycle_overlay(entry_id: int) -> dict[str, Any]:
    item = _lifecycle_state().get(str(int(entry_id))) or {}
    if not isinstance(item, dict):
        return {"weight": 1.0, "frozen": False, "entity_tags": []}
    tags = item.get("entity_tags") or []
    if not isinstance(tags, list):
        tags = []
    return {
        "weight": float(item.get("weight") if item.get("weight") is not None else 1.0),
        "frozen": bool(item.get("frozen")),
        "entity_tags": [str(t).strip() for t in tags if str(t).strip()][:16],
    }


def apply_memory_lifecycle(
    entry_id: int,
    *,
    action: LifecycleAction,
    entity_tags: list[str] | None = None,
) -> dict[str, Any] | None:
    state = _lifecycle_state()
    key = str(int(entry_id))
    current = memory_lifecycle_overlay(entry_id)
    weight = float(current["weight"])
    frozen = bool(current["frozen"])
    tags = list(current["entity_tags"])
    if action == "reinforce":
        weight = min(5.0, weight + 0.25)
    elif action == "weaken":
        weight = max(0.05, weight - 0.25)
    elif action == "freeze":
        frozen = True
    elif action == "unfreeze":
        frozen = False
    elif action == "forget":
        state.pop(key, None)
        _save_lifecycle_state(state)
        return {"id": int(entry_id), "forgotten": True}
    if entity_tags is not None:
        cleaned = [sanitize_prompt_literal(t, max_len=32) for t in entity_tags]
        tags = [t for t in cleaned if t][:16]
    state[key] = {
        "weight": round(weight, 4),
        "frozen": frozen,
        "entity_tags": tags,
        "updated_at": int(time.time()),
    }
    _save_lifecycle_state(state)
    return {"id": int(entry_id), **state[key]}


async def build_memory_stats(*, bot_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    cfg = get_llm_config()
    available = is_llm_memory_store_available()
    prefs = len(list_memory_preferences(bot_id=bot_id, group_id=group_id))
    base = {
        "available": available,
        "rag_enabled": bool(cfg.llm_memory_rag_enabled),
        "preference_count": prefs,
        "max_per_group": int(cfg.llm_memory_max_per_group),
        "rag_top_k": int(cfg.llm_memory_rag_top_k),
        "vector_retrieve": str(cfg.llm_vector_retrieve),
    }
    if not available:
        return {**base, "entry_count": 0, "group_count": 0, "source_counts": {}}
    from pallas.product.llm.memory.store import _use_mongodb_backend, _use_postgresql_backend

    if _use_mongodb_backend():
        if bot_id is None:
            return {**base, "entry_count": 0, "group_count": 0, "source_counts": {}, "sampled": True}
        items = await list_memory_entries(int(bot_id), group_id, limit=200)
        source_counts: dict[str, int] = {}
        for item in items:
            src = str(item.get("source") or "teach")
            source_counts[src] = source_counts.get(src, 0) + 1
        return {
            **base,
            "entry_count": len(items),
            "group_count": len({int(i.get("group_id") or 0) for i in items}),
            "source_counts": source_counts,
            "sampled": True,
        }
    if not _use_postgresql_backend():
        return {**base, "entry_count": 0, "group_count": 0, "source_counts": {}}
    from pallas.core.foundation.db.repository_pg import LlmMemoryEntryRow, get_session

    filters = []
    if bot_id is not None:
        filters.append(LlmMemoryEntryRow.bot_id == int(bot_id))
    if group_id is not None:
        filters.append(LlmMemoryEntryRow.group_id == normalize_group_scope(group_id))
    async with get_session(read_only=True) as session:
        entry_count = int(
            (await session.execute(select(func.count()).select_from(LlmMemoryEntryRow).where(*filters))).scalar_one()
            or 0
        )
        group_count = int(
            (
                await session.execute(select(func.count(func.distinct(LlmMemoryEntryRow.group_id))).where(*filters))
            ).scalar_one()
            or 0
        )
        source_rows = await session.execute(
            select(LlmMemoryEntryRow.source, func.count()).where(*filters).group_by(LlmMemoryEntryRow.source)
        )
        source_counts = {str(src or "teach"): int(cnt) for src, cnt in source_rows.all()}
    return {
        **base,
        "entry_count": entry_count,
        "group_count": group_count,
        "source_counts": source_counts,
    }


async def clear_memory_entries(
    *,
    bot_id: int,
    group_id: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not is_llm_memory_store_available():
        return {"deleted": 0, "dry_run": dry_run, "available": False}
    from pallas.product.llm.memory.store import _use_mongodb_backend, _use_postgresql_backend

    if _use_mongodb_backend():
        from pallas.product.llm.memory.store_mongo import clear_memory_entries_mongo

        return await clear_memory_entries_mongo(bot_id=bot_id, group_id=group_id, dry_run=dry_run)
    if not _use_postgresql_backend():
        return {"deleted": 0, "dry_run": dry_run, "available": False}
    from pallas.core.foundation.db.repository_pg import LlmMemoryEntryRow, get_session

    gid = normalize_group_scope(group_id) if group_id is not None else None
    async with get_session() as session:
        stmt = select(func.count()).select_from(LlmMemoryEntryRow).where(LlmMemoryEntryRow.bot_id == int(bot_id))
        if gid is not None:
            stmt = stmt.where(LlmMemoryEntryRow.group_id == gid)
        count = int((await session.execute(stmt)).scalar_one() or 0)
        if dry_run:
            return {"deleted": count, "dry_run": True, "bot_id": int(bot_id), "group_id": gid}
        del_stmt = delete(LlmMemoryEntryRow).where(LlmMemoryEntryRow.bot_id == int(bot_id))
        if gid is not None:
            del_stmt = del_stmt.where(LlmMemoryEntryRow.group_id == gid)
        await session.execute(del_stmt)
        await session.commit()
    return {"deleted": count, "dry_run": False, "bot_id": int(bot_id), "group_id": gid}


async def preview_memory_retrieve(
    bot_id: int,
    group_id: int | None,
    query: str,
    *,
    cfg: LlmConfig | None = None,
) -> dict[str, Any]:
    c = cfg or get_llm_config()
    hits = await retrieve_memory_hits(bot_id, group_id, query, cfg=c)
    enriched = await enrich_system_with_memory_context(
        "【记忆检索预览】",
        bot_id=bot_id,
        group_id=group_id,
        query_text=query,
        cfg=c,
    )
    return {
        "query": query,
        "hits": [
            {
                "id": item.get("id"),
                "content": item.get("content"),
                "keywords": item.get("keywords"),
                "source": item.get("source"),
                "score": item.get("score"),
                "group_id": item.get("group_id"),
                **(memory_lifecycle_overlay(int(item["id"])) if item.get("id") else {}),
            }
            for item in hits
        ],
        "prompt_text": str(enriched.system_prompt or ""),
        "trace": enriched.trace,
        "hit_count": len(hits),
    }


def list_memory_preferences(
    *,
    bot_id: int | None = None,
    group_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    raw = _read_json(_preferences_path())
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if bot_id is not None and int(item.get("bot_id") or 0) != int(bot_id):
            continue
        if group_id is not None and int(item.get("group_id") or 0) != normalize_group_scope(group_id):
            continue
        out.append(item)
        if len(out) >= max(1, min(int(limit), 200)):
            break
    return out


def upsert_memory_preference(
    *,
    bot_id: int,
    group_id: int | None,
    rule: str,
    polarity: str = "do",
    context: str = "",
    pref_id: str | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    safe_rule = sanitize_prompt_block(rule, max_len=500).strip()
    if not safe_rule:
        raise ValueError("rule required")
    pol = polarity if polarity in _PREF_POLARITIES else "do"
    safe_context = sanitize_prompt_literal(context, max_len=200)
    now = int(time.time())
    payload = _read_json(_preferences_path())
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    target_id = (pref_id or "").strip() or f"pref_{now}_{len(items) + 1}"
    found = False
    updated: dict[str, Any] | None = None
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") != target_id:
            continue
        updated = {
            **item,
            "bot_id": int(bot_id),
            "group_id": normalize_group_scope(group_id),
            "rule": safe_rule,
            "polarity": pol,
            "context": safe_context,
            "is_active": bool(is_active),
            "updated_at": now,
        }
        items[idx] = updated
        found = True
        break
    if not found:
        updated = {
            "id": target_id,
            "bot_id": int(bot_id),
            "group_id": normalize_group_scope(group_id),
            "rule": safe_rule,
            "polarity": pol,
            "context": safe_context,
            "is_active": bool(is_active),
            "created_at": now,
            "updated_at": now,
        }
        items.append(updated)
    payload["items"] = items
    _write_json(_preferences_path(), payload)
    assert updated is not None
    return updated


def delete_memory_preference(pref_id: str) -> bool:
    payload = _read_json(_preferences_path())
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    next_items = [i for i in items if not (isinstance(i, dict) and str(i.get("id") or "") == pref_id)]
    if len(next_items) == len(items):
        return False
    payload["items"] = next_items
    _write_json(_preferences_path(), payload)
    return True


async def list_memory_entity_summaries_async(
    *,
    bot_id: int,
    group_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """从 keywords / lifecycle tags 汇总轻量实体视图（非完整图谱）。"""
    entries = await list_memory_entries(bot_id, group_id, limit=200)
    counters: dict[str, dict[str, Any]] = {}
    for entry in entries:
        tags = [t for t in str(entry.get("keywords") or "").replace("，", ",").split(",") if t.strip()]
        overlay = memory_lifecycle_overlay(int(entry.get("id") or 0)) if entry.get("id") else {}
        tags.extend(list(overlay.get("entity_tags") or []))
        for tag in tags:
            name = sanitize_prompt_literal(tag, max_len=32)
            if not name:
                continue
            bucket = counters.setdefault(
                name.casefold(),
                {"name": name, "mention_count": 0, "entry_ids": [], "weight_sum": 0.0},
            )
            bucket["mention_count"] += 1
            if entry.get("id"):
                bucket["entry_ids"].append(int(entry["id"]))
            bucket["weight_sum"] += float(overlay.get("weight") or 1.0)
    ranked = sorted(counters.values(), key=lambda x: (-int(x["mention_count"]), str(x["name"])))
    return [
        {
            "name": item["name"],
            "mention_count": int(item["mention_count"]),
            "entry_ids": list(item["entry_ids"])[:20],
            "avg_weight": round(float(item["weight_sum"]) / max(1, int(item["mention_count"])), 4),
        }
        for item in ranked[: max(1, min(int(limit), 200))]
    ]
