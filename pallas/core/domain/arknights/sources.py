"""ArknightsGameData / GameResource 公共常量与 URL。"""

from __future__ import annotations

GAMEDATA_REPO = "Kengxxiao/ArknightsGameData"
GAMEDATA_BASE = "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel"
RESOURCE_REPO = "yuanyan3060/ArknightsGameResource"
AVATAR_URL_TEMPLATE = f"https://raw.githubusercontent.com/{RESOURCE_REPO}/main/avatar/{{char_id}}.png"

CHAR_URL = f"{GAMEDATA_BASE}/character_table.json"
SKILL_URL = f"{GAMEDATA_BASE}/skill_table.json"
HANDBOOK_URL = f"{GAMEDATA_BASE}/handbook_table.json"
HANDBOOK_INFO_URL = f"{GAMEDATA_BASE}/handbook_info_table.json"
STAGE_URL = f"{GAMEDATA_BASE}/stage_table.json"
ENEMY_HANDBOOK_URL = f"{GAMEDATA_BASE}/enemy_handbook_table.json"

PAYLOAD_SOURCE = (
    f"{GAMEDATA_REPO} (skill text = levels[-1] + blackboard, 有专精时一般为专三; "
    f"handbook = handbook_info_table; avatar = {RESOURCE_REPO})"
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

PROFESSION_CN: dict[str, str] = {
    "WARRIOR": "近卫",
    "SNIPER": "狙击",
    "TANK": "重装",
    "MEDICINE": "医疗",
    "MEDIC": "医疗",
    "SUPPORT": "辅助",
    "CASTER": "术师",
    "SPECIAL": "特种",
    "PIONEER": "先锋",
    "TOKEN": "傀儡",
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

MIN_AVATAR_BYTES = 512
