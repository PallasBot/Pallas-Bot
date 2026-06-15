"""决斗用六星干员表：resource/arknights/operators_6star.json。"""

from __future__ import annotations

import json
import random
import re
from typing import Any

from nonebot import logger

from src.foundation.paths import resource_dir

_PROF_CN: dict[str, str] = {
    "WARRIOR": "近卫",
    "SNIPER": "狙击",
    "TANK": "重装",
    "MEDICINE": "医疗",
    "MEDIC": "医师",
    "SUPPORT": "辅助",
    "CASTER": "术师",
    "SPECIAL": "特种",
    "TOKEN": "傀儡师",
}

# subProfessionId → 中文
_SUB_PROF_CN: dict[str, str] = {
    "physician": "行医",
    "guard": "铁卫",
    "protector": "守护者",
    "guardian": "不屈者",
    "centurion": "决战者",
    "executor": "处决者",
    "instructor": "教官",
    "lord": "领主",
    "musha": "武者",
    "artsfghter": "术战者",
    "sword": "剑豪",
    "fearless": "无畏者",
    "pioneer": "尖兵",
    "charger": "冲锋手",
    "ritualist": "祭师",
    "bard": "吟游者",
    "corecaster": "中坚术师",
    "splashcaster": "扩散术师",
    "blastcaster": "轰击术师",
    "funnel": "驭械术师",
    "aoe": "阵法术师",
    "slower": "凝滞师",
    "fastshot": "速射手",
    "heavyshot": "重射手",
    "outrange": "广域射手",
    "bombarder": "炮手",
    "besieger": "攻城手",
    "spreadshot": "散射手",
    "underwatcher": "强攻手",
    "ambusher": "伏击客",
    "hookman": "钩索师",
    "pusher": "推击手",
    "trapmaster": "陷阱师",
    "geek": "怪杰",
    "merchant": "行商",
    "craftsman": "工匠",
    "dollcharger": "傀儡师",
    "breaker": "破坏者",
    "unyield": "不屈者",
    "cloning": "替身",
    "carrier": "要塞",
    "reaper": "收割者",
    "fortress": "要塞",
    "hexer": "咒愈师",
    "mystic": "秘术师",
    "chainwar": "链术师",
    "whip": "驭法铁卫",
    "hammer": "铁卫",
}


def operators_json_path():
    """六星表 JSON 路径。"""
    return resource_dir("arknights") / "operators_6star.json"


def find_operator_by_id(op_id: str) -> dict[str, Any] | None:
    data = get_operators_payload()
    ops = data.get("operators")
    if not isinstance(ops, list):
        return None
    needle = str(op_id).strip()
    for op in ops:
        if isinstance(op, dict) and str(op.get("id", "")).strip() == needle:
            return op
    return None


_operators_payload: dict[str, Any] | None = None


def reload_operators_cache() -> None:
    """下次读取时重新加载 JSON。"""
    global _operators_payload
    _operators_payload = None


def get_operators_payload() -> dict[str, Any]:
    """读入并缓存 operators_6star 根对象。"""
    global _operators_payload
    if _operators_payload is None:
        path = operators_json_path()
        if not path.is_file():
            logger.warning(
                f"duel arknights: missing {path}, will auto-sync if enabled or run scripts/fetch_arknights_duel_data.py"
            )
            _operators_payload = {"operators": [], "count": 0}
        else:
            try:
                _operators_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as err:
                logger.error(f"duel arknights: load fail {path}: {err}")
                _operators_payload = {"operators": [], "count": 0}
    return _operators_payload


def pick_random_operator() -> dict[str, Any] | None:
    """随机一名六星干员字典。"""
    data = get_operators_payload()
    ops = data.get("operators")
    if not isinstance(ops, list) or not ops:
        return None
    return random.choice(ops)


PALLAS_OPERATOR_NAME = "帕拉斯"


def find_operator_by_name(name: str) -> dict[str, Any] | None:
    data = get_operators_payload()
    ops = data.get("operators")
    if not isinstance(ops, list):
        return None
    for op in ops:
        if isinstance(op, dict) and str(op.get("name", "")).strip() == name:
            return op
    return None


def pick_operator_for_intrusion(*, pallas_chance: float = 0.06) -> dict[str, Any] | None:
    """乱入干员；小概率固定帕拉斯。"""
    if random.random() < pallas_chance:
        pallas = find_operator_by_name(PALLAS_OPERATOR_NAME)
        if pallas:
            return pallas
    return pick_random_operator()


def sub_profession_cn(sid: str) -> str:
    """子职业 id → 中文名。"""
    if not sid:
        return ""
    return _SUB_PROF_CN.get(sid, sid)


def skill_description_for_display(raw: str, *, max_len: int = 240) -> str:
    """旧版未解析简述：剥标签后仍脏则返回空。"""
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.replace("\\n", " ")
    for _ in range(100):
        nxt = re.sub(r"<[^>]+>", "", s)
        if nxt == s:
            break
        s = nxt
    s = re.sub(r"\{[^}]*\}", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    if "<" in s or "{" in s:
        return ""
    if re.search(r"@ba\.|\$ba\.", s):
        return ""
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def profession_cn(code: str) -> str:
    """职业代码 → 中文。"""
    return _PROF_CN.get(str(code), str(code))


_HEAL_HINT = (
    "治疗",
    "回复",
    "恢复",
    "生命",
    "治愈",
    "疗伤",
    "缓回",
    "自愈",
    "医疗",
    "回血",
    "治疗量",
    "每秒恢复",
    "回复生命",
    "每秒回复",
    "持续回复",
)
_ATTACK_HINT = (
    "伤害",
    "法术伤害",
    "物理伤害",
    "攻击力",
    "相当于攻击力",
    "造成",
    "轰炸",
    "溅射",
    "打击",
    "损伤",
    "法术",
    "物理",
    "晕眩",
    "束缚",
    "沉默",
)


def classify_picked_skill_kind(name: str, desc: str, profession: str) -> str:
    """按简述关键词粗分 heal / attack / neutral。"""
    blob = f"{name} {desc}"
    heal_n = sum(1 for k in _HEAL_HINT if k in blob)
    atk_n = sum(1 for k in _ATTACK_HINT if k in blob)
    if profession in ("MEDIC", "MEDICINE"):
        heal_n += 1
    if heal_n > atk_n:
        return "heal"
    if atk_n > heal_n:
        return "attack"
    return "neutral"


def build_intrusion_ctx(op: dict[str, Any]) -> dict[str, str]:
    """干员 dict → 乱入占位符；<SK> 等为至多三技能中随机一条。"""
    skills = op.get("skills")
    s1_name = s1_desc = s2_name = s2_desc = s3_name = s3_desc = ""
    if isinstance(skills, list):
        if len(skills) >= 1 and isinstance(skills[0], dict):
            s1_name = str(skills[0].get("name", "") or "")
            s1_desc = skill_description_for_display(str(skills[0].get("description", "") or ""))
        if len(skills) >= 2 and isinstance(skills[1], dict):
            s2_name = str(skills[1].get("name", "") or "")
            s2_desc = skill_description_for_display(str(skills[1].get("description", "") or ""))
        if len(skills) >= 3 and isinstance(skills[2], dict):
            s3_name = str(skills[2].get("name", "") or "")
            s3_desc = skill_description_for_display(str(skills[2].get("description", "") or ""))
    prof = str(op.get("profession", ""))
    sub_id = str(op.get("sub_profession_id") or op.get("subProfessionId") or "")

    sk_name = sk_desc = sk_label = ""
    kind = "neutral"
    kind_cn = "中性"
    pi = -1
    if isinstance(skills, list):
        cand = [i for i in range(min(3, len(skills))) if isinstance(skills[i], dict)]
        if cand:
            pi = random.choice(cand)
            row = skills[pi]
            sk_name = str(row.get("name", "") or "")
            sk_desc = skill_description_for_display(str(row.get("description", "") or ""))
            ord_cn = ("一", "二", "三")[pi]
            sk_label = f"其{ord_cn}技能"
            kind = classify_picked_skill_kind(sk_name, sk_desc, prof)
            kind_cn = {"heal": "治疗向", "attack": "攻击向", "neutral": "中性"}.get(kind, "中性")

    return {
        "op_id": str(op.get("id", "")),
        "name": str(op.get("name", "") or "").strip(),
        "profession": prof,
        "profession_cn": profession_cn(prof),
        "sub_profession_id": sub_id,
        "sub_profession_cn": sub_profession_cn(sub_id),
        "skill1_name": s1_name,
        "skill1_desc": s1_desc,
        "skill2_name": s2_name,
        "skill2_desc": s2_desc,
        "skill3_name": s3_name,
        "skill3_desc": s3_desc,
        "picked_skill_name": sk_name,
        "picked_skill_desc": sk_desc,
        "picked_skill_label": sk_label,
        "picked_skill_slot": str(pi + 1) if pi >= 0 else "",
        "picked_skill_kind": kind,
        "picked_skill_kind_cn": kind_cn,
        "avatar_url": str(op.get("avatar_url", "") or ""),
        "is_pallas": "1" if str(op.get("name", "") or "").strip() == PALLAS_OPERATOR_NAME else "",
    }


async def resolve_operator_avatar_image(op_id: str) -> bytes | None:
    """乱入发图：仅 resource 本地 PNG 的 bytes，不回退远程 URL。"""
    cid = str(op_id or "").strip()
    if not cid:
        return None
    from src.domain.arknights.duel_sync import operator_avatar_bytes
    from src.plugins.duel.config import plugin_config

    data = operator_avatar_bytes(cid)
    if data:
        return data
    if plugin_config.duel_avatar_download_on_use:
        from src.shared.utils.arknights_duel_resource import ensure_duel_avatar

        path = await ensure_duel_avatar(cid, allow_download=True)
        if path:
            return operator_avatar_bytes(cid)
    logger.warning(f"duel arknights: no local avatar for {cid}")
    return None
