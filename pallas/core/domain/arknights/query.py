"""干员结构化查询（决斗 JSON 同源）。"""

from __future__ import annotations

from typing import Any

from pallas.core.domain.arknights.duel_sync import load_kb_operators_payload
from pallas.core.domain.arknights.sync import load_enemies_payload


def list_operators(*, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = payload if payload is not None else load_kb_operators_payload()
    if not data:
        return []
    ops = data.get("operators")
    if not isinstance(ops, list):
        return []
    return [op for op in ops if isinstance(op, dict)]


def operator_name_variants(name: str) -> tuple[str, ...]:
    """干员名查询变体：常见「丝/斯」混写。"""
    text = (name or "").strip()
    if not text:
        return ()
    variants = [text]
    if "斯" in text:
        variants.append(text.replace("斯", "丝"))
    if "丝" in text:
        variants.append(text.replace("丝", "斯"))
    out: list[str] = []
    for item in variants:
        if item and item not in out:
            out.append(item)
    return tuple(out)


def find_operator_raw(name: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    needles = operator_name_variants(name)
    if not needles:
        return None
    for op in list_operators(payload=payload):
        op_name = str(op.get("name", "")).strip()
        if op_name in needles:
            return op
    return None


def summarize_operator(op: dict[str, Any], *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = payload if payload is not None else load_kb_operators_payload()
    version = ""
    if isinstance(data, dict):
        version = str(data.get("source") or data.get("rarity_filter") or "")
    skills = op.get("skills") if isinstance(op.get("skills"), list) else []
    skill_brief = [
        {
            "index": i + 1,
            "name": str(s.get("name", "") if isinstance(s, dict) else ""),
            "description": str(s.get("description", "") if isinstance(s, dict) else "")[:120],
        }
        for i, s in enumerate(skills[:3])
    ]
    return {
        "id": op.get("id"),
        "name": op.get("name"),
        "rarity": op.get("rarity"),
        "profession_cn": op.get("profession_cn") or op.get("profession"),
        "nation_cn": op.get("nation_cn") or op.get("nation_id"),
        "display_number": op.get("display_number"),
        "item_desc": op.get("item_desc"),
        "item_usage": op.get("item_usage"),
        "tags": op.get("tags") if isinstance(op.get("tags"), list) else [],
        "skills": skill_brief,
        "handbook_lines": op.get("handbook_lines") if isinstance(op.get("handbook_lines"), list) else [],
        "data_version": version,
    }


def query_operator(name: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    op = find_operator_raw(name, payload=payload)
    if not op:
        return None
    return summarize_operator(op, payload=payload)


def search_operators(query: str, *, limit: int = 5, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    needles = [n.lower() for n in operator_name_variants(query)]
    if not needles or limit <= 0:
        return []
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for op in list_operators(payload=payload):
        name = str(op.get("name", "")).strip()
        name_lower = name.lower()
        if not any(needle in name_lower for needle in needles):
            continue
        if name in seen:
            continue
        seen.add(name)
        hits.append(summarize_operator(op, payload=payload))
        if len(hits) >= limit:
            break
    return hits


def query_operator_skill(
    name: str,
    skill_index: int,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    op = find_operator_raw(name, payload=payload)
    if not op:
        return None
    skills = op.get("skills")
    if not isinstance(skills, list) or not skills:
        return None
    idx = int(skill_index)
    if idx < 1 or idx > len(skills):
        return None
    skill = skills[idx - 1]
    if not isinstance(skill, dict):
        return None
    summary = summarize_operator(op, payload=payload)
    return {
        "operator": summary.get("name"),
        "skill_index": idx,
        "skill_name": skill.get("name", ""),
        "description": skill.get("description", ""),
        "data_version": summary.get("data_version"),
    }


def list_enemies(*, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = payload if payload is not None else load_enemies_payload()
    if not data:
        return []
    enemies = data.get("enemies")
    if not isinstance(enemies, list):
        return []
    return [row for row in enemies if isinstance(row, dict)]


def find_enemy_raw(name: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    needle = (name or "").strip()
    if not needle:
        return None
    for row in list_enemies(payload=payload):
        if str(row.get("name", "")).strip() == needle:
            return row
    return None


def summarize_enemy(row: dict[str, Any], *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = payload if payload is not None else load_enemies_payload()
    version = ""
    if isinstance(data, dict):
        version = str(data.get("source") or "")
    abilities = row.get("abilities") if isinstance(row.get("abilities"), list) else []
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "level": row.get("level"),
        "description": row.get("description"),
        "abilities": [str(a) for a in abilities[:5]],
        "data_version": version,
    }


def query_enemy(name: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    row = find_enemy_raw(name, payload=payload)
    if not row:
        return None
    return summarize_enemy(row, payload=payload)


def search_enemies(query: str, *, limit: int = 5, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    needle = (query or "").strip().lower()
    if not needle or limit <= 0:
        return []
    hits: list[dict[str, Any]] = []
    for row in list_enemies(payload=payload):
        name = str(row.get("name", "")).strip()
        if needle in name.lower():
            hits.append(summarize_enemy(row, payload=payload))
            if len(hits) >= limit:
                break
    return hits
