"""从 ArknightsGameData 拉取 character/skill 表，生成决斗用六星瘦身 JSON 到 resource/arknights/。"""

from __future__ import annotations

import json
import operator
import sys
import urllib.request
from pathlib import Path

# 仓库根：scripts/ 的上级（供 `from src...` 解析）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.arknights_skill_text import skill_last_level_plain  # noqa: E402

OUT_DIR = ROOT / "resource" / "arknights"
OUT_FILE = OUT_DIR / "operators_6star.json"

CHAR_URL = (
    "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/character_table.json"
)
SKILL_URL = "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/skill_table.json"

# character_table.nationId → 中文国/地区名（无独立 nation 表，与泰拉设定常用译名对齐）
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

PROFESSION_CN = {
    "WARRIOR": "近卫",
    "SNIPER": "狙击",
    "TANK": "重装",
    "MEDICINE": "医疗",
    "MEDIC": "医疗",
    "SUPPORT": "辅助",
    "CASTER": "术师",
    "SPECIAL": "特种",
    "TOKEN": "傀儡",
}


def fetch_json(url: str) -> dict:
    """GET JSON 并解析为 dict。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Pallas-Bot-ark-sync/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def skill_name_and_desc_m3(skill_table: dict, skill_id: str) -> tuple[str, str]:
    """技能名与说明取 levels 最后一档（有专精时一般为专三），说明为黑板替换后的纯文本。"""
    info = skill_table.get(skill_id)
    if not info or not isinstance(info, dict):
        return "", ""
    levels = info.get("levels")
    if not isinstance(levels, list) or not levels:
        return "", ""
    last = levels[-1]
    if not isinstance(last, dict):
        return "", ""
    name = str(last.get("name", "") or "")
    desc = skill_last_level_plain(info, max_len=240)
    return name, desc


def main() -> int:
    """拉表并写 operators_6star.json。"""
    print("fetching character_table ...")
    char_table = fetch_json(CHAR_URL)
    print("fetching skill_table ...")
    skill_table = fetch_json(SKILL_URL)

    operators: list[dict] = []
    for char_id, row in char_table.items():
        if not isinstance(row, dict):
            continue
        if not str(char_id).startswith("char_"):
            continue
        if row.get("rarity") != "TIER_6":
            continue
        name = row.get("name")
        if not name or not isinstance(name, str):
            continue
        prof = str(row.get("profession", "WARRIOR"))
        sub_prof = str(row.get("subProfessionId") or "")
        skills_raw = row.get("skills")
        skills_out: list[dict] = []
        if isinstance(skills_raw, list):
            for slot in skills_raw[:3]:
                if not isinstance(slot, dict):
                    continue
                sid = slot.get("skillId")
                if not sid:
                    continue
                sn, sd = skill_name_and_desc_m3(skill_table, str(sid))
                skills_out.append({"skill_id": str(sid), "name": sn, "description": sd})

        nation_id = str(row.get("nationId") or "").strip()
        operators.append({
            "id": str(char_id),
            "name": name.strip(),
            "profession": prof,
            "profession_cn": PROFESSION_CN.get(prof, prof),
            "sub_profession_id": sub_prof,
            "nation_id": nation_id,
            "nation_cn": NATION_CN.get(nation_id, ""),
            "skills": skills_out,
            "avatar_url": f"https://raw.githubusercontent.com/yuanyan3060/ArknightsGameResource/main/avatar/{char_id}.png",
        })

    operators.sort(key=operator.itemgetter("id"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": (
            "Kengxxiao/ArknightsGameData (skill text = levels[-1] + blackboard, 有专精时一般为专三) "
            "+ yuanyan3060/ArknightsGameResource (avatar path only)"
        ),
        "rarity_filter": "TIER_6",
        "count": len(operators),
        "operators": operators,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_FILE} ({len(operators)} operators)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
