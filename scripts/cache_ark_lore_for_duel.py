"""维护者用：拉取 ArknightsGameData 官设摘录到 .cache/duel_ark_lore/（已 gitignore），供撰写决斗事件参考。"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".cache" / "duel_ark_lore"

CHAR_URL = (
    "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/character_table.json"
)
HANDBOOK_URL = (
    "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/handbook_table.json"
)
STAGE_URL = (
    "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/stage_table.json"
)

NATION_CN: dict[str, str] = {
    "yan": "炎",
    "lungmen": "龙门",
    "rhodes": "罗德岛",
    "victoria": "维多利亚",
    "columbia": "哥伦比亚",
    "ursus": "乌萨斯",
    "leithanien": "莱塔尼亚",
    "kazimierz": "卡西米尔",
    "kjerag": "谢拉格",
    "sargon": "萨尔贡",
    "siracusa": "叙拉古",
    "laterano": "拉特兰",
    "iberia": "伊比利亚",
    "higashi": "东",
    "sami": "萨米",
    "egir": "阿戈尔",
    "rim": "雷姆必拓",
    "minos": "米诺斯",
}

NATION_KEYWORDS: dict[str, list[str]] = {
    "yan": ["炎", "玉门", "大炎", "司岁台", "岁"],
    "lungmen": ["龙门", "近卫局"],
    "victoria": ["维多利亚", "伦蒂尼姆", "蒸汽"],
    "kjerag": ["谢拉格", "雪山", "圣女", "喀兰"],
    "kazimierz": ["卡西米尔", "骑士", "竞技场", "监正会"],
    "leithanien": ["莱塔尼亚", "金律", "高塔", "巫王"],
    "sami": ["萨米", "雪原", "邪魔", "独眼巨人"],
    "egir": ["阿戈尔", "深海", "恐鱼", "海嗣"],
    "rim": ["雷姆必拓", "矿", "荒地"],
    "minos": ["米诺斯", "英雄", "帕拉斯"],
    "sargon": ["萨尔贡", "黄沙", "王酋"],
    "siracusa": ["叙拉古", "家族", "沃尔西尼"],
    "ursus": ["乌萨斯", "冻原", "切尔诺伯格"],
}


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Pallas-Bot-lore-cache/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def strip_rich(s: str, max_len: int = 320) -> str:
    t = re.sub(r"<[^>]+>", "", s.replace("\\n", " "))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def handbook_info_lines(hb_row: dict, limit: int = 3) -> list[str]:
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
        text = strip_rich(str(block.get("storyText", "") or ""), 240)
        if text:
            title = str(block.get("storyTitle", "") or "").strip()
            lines.append(f"{title}：{text}" if title else text)
            if len(lines) >= limit:
                return lines
    return lines


def collect_stage_snippets(stages: dict, nation_id: str, limit: int = 2) -> list[str]:
    keys = NATION_KEYWORDS.get(nation_id, [NATION_CN.get(nation_id, "")])
    out: list[str] = []
    for s in stages.values():
        if not isinstance(s, dict):
            continue
        desc = strip_rich(str(s.get("description", "") or ""), 200)
        if not desc or len(desc) < 12:
            continue
        if any(k in desc for k in keys if k):
            code = str(s.get("code", "") or "")
            name = str(s.get("name", "") or "")
            snippet = f"{code} {name}：{desc}"
            if snippet not in out:
                out.append(snippet)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    print("fetching tables ...")
    char_table = fetch_json(CHAR_URL)
    handbook = fetch_json(HANDBOOK_URL)
    stage_table = fetch_json(STAGE_URL)
    stages = stage_table.get("stages") or {}

    by_nation: dict[str, list[dict]] = defaultdict(list)
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
        if char_id in handbook and isinstance(handbook[char_id], dict):
            hb_lines = handbook_info_lines(handbook[char_id])
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

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "Kengxxiao/ArknightsGameData zh_CN excel",
        "nation_cn": NATION_CN,
        "by_nation": dict(by_nation),
        "stage_snippets": stage_by_nation,
    }
    (CACHE_DIR / "by_nation.json").write_text(
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
            lines.append(f"- 关卡：{sn}\n")
        for o in (six or ops)[:5]:
            lines.append(f"### {o['name']}\n")
            if o["item_desc"]:
                lines.append(f"- itemDesc：{o['item_desc']}\n")
            if o["item_usage"]:
                lines.append(f"- itemUsage：{o['item_usage']}\n")
            for hl in o["handbook_lines"][:2]:
                lines.append(f"- 档案：{hl}\n")

    (CACHE_DIR / "REFERENCE.md").write_text("".join(lines), encoding="utf-8")
    print(f"wrote {CACHE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
