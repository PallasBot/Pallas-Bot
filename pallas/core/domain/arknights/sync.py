"""方舟数据统一同步：干员表、头像、档案摘录、敌人图鉴、维护者 lore 缓存。"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003
from typing import Any

from pallas.core.domain.arknights.duel_sync import (
    OPERATORS_JSON,
    OPERATORS_KB_JSON,
    fetch_json_sync,
    load_operators_payload,
    operator_ids_from_payload,
    sync_avatars_sync,
    write_operators_json,
)
from pallas.core.domain.arknights.duel_sync import build_operators_payload as build_operators_core
from pallas.core.domain.arknights.sources import (
    CHAR_URL,
    ENEMY_HANDBOOK_URL,
    GAMEDATA_REPO,
    HANDBOOK_INFO_URL,
    NATION_CN,
    NATION_KEYWORDS,
    SKILL_URL,
    STAGE_URL,
)
from pallas.core.foundation.config.repo_settings import repo_root
from pallas.core.foundation.paths import resource_dir

ARKNIGHTS_DIR = resource_dir("arknights")
ENEMIES_JSON = ARKNIGHTS_DIR / "enemies_handbook.json"
MAINTAINER_LORE_DIR = repo_root() / ".cache" / "duel_ark_lore"


def strip_rich(text: str, max_len: int = 320) -> str:
    t = re.sub(r"<[^>]+>", "", text.replace("\\n", " "))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def handbook_info_lines(hb_row: dict[str, Any], limit: int = 3) -> list[str]:
    lines: list[str] = []
    for block in hb_row.get("infoTextAudio") or []:
        if not isinstance(block, dict):
            continue
        for item in block.get("infoList") or []:
            if not isinstance(item, dict):
                continue
            text = strip_rich(str(item.get("infoText", "") or ""), 200)
            if text and text not in lines:
                lines.append(text)
            if len(lines) >= limit:
                return lines
    for block in hb_row.get("storyTextAudio") or []:
        if not isinstance(block, dict):
            continue
        title = str(block.get("storyTitle", "") or "").strip()
        stories = block.get("stories")
        if isinstance(stories, list):
            for story in stories:
                if not isinstance(story, dict):
                    continue
                text = strip_rich(str(story.get("storyText", "") or ""), 320)
                if not text:
                    continue
                line = f"{title}：{text}" if title else text
                if line not in lines:
                    lines.append(line)
                if len(lines) >= limit:
                    return lines
            continue
        text = strip_rich(str(block.get("storyText", "") or ""), 240)
        if text:
            line = f"{title}：{text}" if title else text
            if line not in lines:
                lines.append(line)
            if len(lines) >= limit:
                return lines
    return lines


def normalize_handbook_dict(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    handbook = raw.get("handbookDict")
    if isinstance(handbook, dict) and handbook:
        return handbook
    return raw


def attach_handbook_lines(
    operators: list[dict[str, Any]],
    handbook_table: dict[str, Any] | None,
    *,
    handbook_lines_limit: int = 5,
) -> int:
    if not isinstance(handbook_table, dict):
        return 0
    enriched = 0
    for op in operators:
        if not isinstance(op, dict):
            continue
        char_id = str(op.get("id") or "")
        hb_row = handbook_table.get(char_id)
        if not isinstance(hb_row, dict):
            continue
        lines = handbook_info_lines(hb_row, limit=handbook_lines_limit)
        if lines:
            op["handbook_lines"] = lines
            enriched += 1
    return enriched


def collect_stage_snippets(stages: dict[str, Any], nation_id: str, limit: int = 2) -> list[str]:
    keys = NATION_KEYWORDS.get(nation_id, [NATION_CN.get(nation_id, "")])
    out: list[str] = []
    for stage in stages.values():
        if not isinstance(stage, dict):
            continue
        desc = strip_rich(str(stage.get("description", "") or ""), 200)
        if not desc or len(desc) < 12:
            continue
        if any(k in desc for k in keys if k):
            code = str(stage.get("code", "") or "")
            name = str(stage.get("name", "") or "")
            snippet = f"{code} {name}：{desc}"
            if snippet not in out:
                out.append(snippet)
        if len(out) >= limit:
            break
    return out


def build_operators_payload(
    char_table: dict[str, Any],
    skill_table: dict[str, Any],
    handbook_table: dict[str, Any] | None = None,
    *,
    rarity_filter: str | None = "TIER_6",
    handbook_lines_limit: int = 5,
) -> dict[str, Any]:
    payload = build_operators_core(char_table, skill_table, rarity_filter=rarity_filter)
    ops = payload.get("operators")
    if not isinstance(ops, list):
        return payload
    if handbook_table:
        payload["handbook_enriched"] = True
        payload["handbook_profiles"] = attach_handbook_lines(
            ops,
            handbook_table,
            handbook_lines_limit=handbook_lines_limit,
        )
    return payload


def build_enemies_payload(enemy_table: dict[str, Any]) -> dict[str, Any]:
    raw = enemy_table.get("enemyData")
    if not isinstance(raw, dict):
        raw = enemy_table
    enemies: list[dict[str, Any]] = []
    for enemy_id, row in raw.items():
        if not isinstance(row, dict):
            continue
        if row.get("hideInHandbook"):
            continue
        name = str(row.get("name", "") or "").strip()
        if not name:
            continue
        abilities: list[str] = []
        for item in row.get("abilityList") or []:
            if isinstance(item, dict):
                text = str(item.get("text", "") or "").strip()
                if text:
                    abilities.append(text)
        enemies.append({
            "id": str(enemy_id),
            "name": name,
            "level": str(row.get("enemyLevel", "") or ""),
            "description": strip_rich(str(row.get("description", "") or ""), 400),
            "abilities": abilities,
        })
    enemies.sort(key=lambda e: (e.get("name", ""), e.get("id", "")))
    return {
        "source": f"{GAMEDATA_REPO} enemy_handbook_table",
        "count": len(enemies),
        "enemies": enemies,
    }


def write_enemies_json(payload: dict[str, Any], path: Path | None = None) -> Path:
    dest = path or ENEMIES_JSON
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def load_enemies_payload(path: Path | None = None) -> dict[str, Any] | None:
    dest = path or ENEMIES_JSON
    if not dest.is_file():
        return None
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_maintainer_lore_cache(
    char_table: dict[str, Any],
    handbook_table: dict[str, Any],
    stage_table: dict[str, Any],
    *,
    cache_dir: Path | None = None,
) -> Path:
    stages = stage_table.get("stages") or {}
    by_nation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for char_id, row in char_table.items():
        if not isinstance(row, dict) or not str(char_id).startswith("char_"):
            continue
        nation = str(row.get("nationId") or "").strip()
        if not nation:
            continue
        name = str(row.get("name", "") or "").strip()
        if not name:
            continue
        hb_lines: list[str] = []
        hb_row = handbook_table.get(char_id)
        if isinstance(hb_row, dict):
            hb_lines = handbook_info_lines(hb_row)
        by_nation[nation].append({
            "id": char_id,
            "name": name,
            "rarity": row.get("rarity", ""),
            "item_desc": strip_rich(str(row.get("itemDesc", "") or ""), 400),
            "item_usage": strip_rich(str(row.get("itemUsage", "") or ""), 200),
            "handbook_lines": hb_lines,
        })

    stage_by_nation = {nid: collect_stage_snippets(stages, nid) for nid in NATION_KEYWORDS}

    for nation in by_nation:
        by_nation[nation].sort(
            key=lambda e: (0 if e["rarity"] == "TIER_6" else 1, e["name"]),
        )

    dest_dir = cache_dir or MAINTAINER_LORE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": f"{GAMEDATA_REPO} zh_CN excel",
        "nation_cn": NATION_CN,
        "by_nation": dict(by_nation),
        "stage_snippets": stage_by_nation,
    }
    (dest_dir / "by_nation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = ["# 决斗事件撰写参考（临时缓存，勿提交）\n"]
    for nid in NATION_KEYWORDS:
        cn = NATION_CN.get(nid, nid)
        ops = by_nation.get(nid, [])
        six = [o for o in ops if o["rarity"] == "TIER_6"]
        lines.append(f"\n## {cn} ({nid}) — 六星 {len(six)} / 全 {len(ops)}\n")
        for sn in stage_by_nation.get(nid, []):
            lines.append(f"- 关卡：{sn}\n")  # noqa: PERF401
        for op in (six or ops)[:5]:
            lines.append(f"### {op['name']}\n")
            if op["item_desc"]:
                lines.append(f"- itemDesc：{op['item_desc']}\n")
            if op["item_usage"]:
                lines.append(f"- itemUsage：{op['item_usage']}\n")
            for hl in op["handbook_lines"][:2]:
                lines.append(f"- 档案：{hl}\n")  # noqa: PERF401

    (dest_dir / "REFERENCE.md").write_text("".join(lines), encoding="utf-8")
    return dest_dir


@dataclass
class ArknightsSyncPlan:
    operators: bool = True
    operators_kb_full: bool = False
    avatars: bool = True
    handbook_enrich: bool = False
    enemies: bool = False
    maintainer_lore: bool = False
    avatars_only: bool = False
    operators_path: Path | None = None
    operators_kb_path: Path | None = None
    enemies_path: Path | None = None


@dataclass
class ArknightsSyncResult:
    operators_count: int = 0
    operators_path: Path | None = None
    operators_kb_count: int = 0
    operators_kb_path: Path | None = None
    avatars_ok: int = 0
    avatars_tried: int = 0
    enemies_count: int = 0
    enemies_path: Path | None = None
    maintainer_lore_dir: Path | None = None
    messages: list[str] = field(default_factory=list)


def duel_sync_plan(*, avatars: bool = True, avatars_only: bool = False) -> ArknightsSyncPlan:
    """决斗缺表/缺头像时使用的最小同步。"""
    return ArknightsSyncPlan(
        operators=not avatars_only,
        avatars=avatars,
        avatars_only=avatars_only,
    )


def kb_sync_plan(*, avatars: bool = False) -> ArknightsSyncPlan:
    """知识库：全星级干员 + 档案 + 敌人图鉴（另写六星表供决斗）。"""
    return ArknightsSyncPlan(
        operators=True,
        operators_kb_full=True,
        avatars=avatars,
        handbook_enrich=True,
        enemies=True,
    )


def full_sync_plan() -> ArknightsSyncPlan:
    return ArknightsSyncPlan(
        operators=True,
        operators_kb_full=True,
        avatars=True,
        handbook_enrich=True,
        enemies=True,
        maintainer_lore=True,
    )


def run_arknights_sync(plan: ArknightsSyncPlan) -> ArknightsSyncResult:
    result = ArknightsSyncResult()
    char_table: dict[str, Any] | None = None
    skill_table: dict[str, Any] | None = None
    handbook_table: dict[str, Any] | None = None
    stage_table: dict[str, Any] | None = None
    enemy_table: dict[str, Any] | None = None

    need_char = plan.operators or plan.handbook_enrich or plan.maintainer_lore
    need_handbook = plan.handbook_enrich or plan.maintainer_lore
    need_stage = plan.maintainer_lore
    need_enemy = plan.enemies

    if plan.avatars_only:
        payload = load_operators_payload(plan.operators_path)
        if not payload:
            msg = f"missing {plan.operators_path or OPERATORS_JSON}, sync operators first"
            result.messages.append(msg)
            return result
        operator_ids = operator_ids_from_payload(payload)
        result.operators_count = int(payload.get("count") or 0)
        result.operators_path = plan.operators_path or OPERATORS_JSON
    elif need_char:
        result.messages.append("fetching character_table + skill_table ...")
        char_table = fetch_json_sync(CHAR_URL)
        skill_table = fetch_json_sync(SKILL_URL)
        if need_handbook:
            result.messages.append("fetching handbook_info_table ...")
            handbook_table = normalize_handbook_dict(fetch_json_sync(HANDBOOK_INFO_URL))
        if need_stage:
            result.messages.append("fetching stage_table ...")
            stage_table = fetch_json_sync(STAGE_URL)
        if need_enemy:
            result.messages.append("fetching enemy_handbook_table ...")
            enemy_table = fetch_json_sync(ENEMY_HANDBOOK_URL)

        if plan.operators:
            handbook_data = handbook_table if plan.handbook_enrich else None
            if plan.operators_kb_full:
                payload_full = build_operators_payload(
                    char_table,
                    skill_table,
                    handbook_data,
                    rarity_filter=None,
                )
                kb_dest = write_operators_json(
                    payload_full,
                    plan.operators_kb_path or OPERATORS_KB_JSON,
                )
                result.operators_kb_count = int(payload_full.get("count") or 0)
                result.operators_kb_path = kb_dest
                profiles = int(payload_full.get("handbook_profiles") or 0)
                result.messages.append(
                    f"wrote {kb_dest} ({result.operators_kb_count} operators, handbook_profiles={profiles})",
                )

            payload = build_operators_payload(
                char_table,
                skill_table,
                handbook_data,
                rarity_filter="TIER_6",
            )
            dest = write_operators_json(payload, plan.operators_path)
            result.operators_count = int(payload.get("count") or 0)
            result.operators_path = dest
            result.messages.append(f"wrote {dest} ({result.operators_count} operators)")
            operator_ids = operator_ids_from_payload(payload)
        else:
            operator_ids = []

        if plan.enemies and enemy_table is not None:
            enemies_payload = build_enemies_payload(enemy_table)
            dest = write_enemies_json(enemies_payload, plan.enemies_path)
            result.enemies_count = int(enemies_payload.get("count") or 0)
            result.enemies_path = dest
            result.messages.append(f"wrote {dest} ({result.enemies_count} enemies)")

        if plan.maintainer_lore and char_table and handbook_table and stage_table:
            lore_dir = write_maintainer_lore_cache(char_table, handbook_table, stage_table)
            result.maintainer_lore_dir = lore_dir
            result.messages.append(f"wrote maintainer lore cache {lore_dir}")
    else:
        operator_ids = []
        if need_handbook:
            handbook_table = normalize_handbook_dict(fetch_json_sync(HANDBOOK_INFO_URL))
        if need_enemy:
            enemy_table = fetch_json_sync(ENEMY_HANDBOOK_URL)
            if plan.enemies:
                enemies_payload = build_enemies_payload(enemy_table)
                dest = write_enemies_json(enemies_payload, plan.enemies_path)
                result.enemies_count = int(enemies_payload.get("count") or 0)
                result.enemies_path = dest
                result.messages.append(f"wrote {dest} ({result.enemies_count} enemies)")

    if plan.avatars and operator_ids:
        result.messages.append(f"syncing avatars ({len(operator_ids)} operators) ...")
        ok, tried = sync_avatars_sync(operator_ids, missing_only=True)
        result.avatars_ok = ok
        result.avatars_tried = tried
        result.messages.append(f"avatars: ok={ok} tried={tried}")

    return result


def sync_operators_json_sync(*, path: Path | None = None, handbook_enrich: bool = False) -> dict[str, Any]:
    """兼容旧 API：仅同步六星干员表。"""
    plan = ArknightsSyncPlan(
        operators=True,
        avatars=False,
        handbook_enrich=handbook_enrich,
        operators_path=path,
    )
    run_arknights_sync(plan)
    payload = load_operators_payload(path)
    if not payload:
        msg = "operators sync produced no payload"
        raise RuntimeError(msg)
    return payload
