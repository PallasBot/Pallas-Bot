"""Canonical occasion tags used by persona expression records."""

from __future__ import annotations

from enum import StrEnum


class OccasionTag(StrEnum):
    PROVOCATION = "provocation"
    BANTER = "banter"
    SMALLTALK = "smalltalk"
    VENTING = "venting"
    GROUP_THREADING = "group_threading"
    LIGHT_HELP = "light_help"
    SELF_REFERENCE = "self_reference"
    SENTENCE_TAIL = "sentence_tail"
    GREETING = "greeting"
    WARM_REPLY = "warm_reply"
    AGREEMENT = "agreement"


_OCCASION_ALIASES = {
    "接梗玩笑": OccasionTag.BANTER,
    "玩笑": OccasionTag.BANTER,
    "接梗": OccasionTag.BANTER,
    "吐槽": OccasionTag.VENTING,
    "顶嘴吐槽": OccasionTag.PROVOCATION,
    "安抚情绪": OccasionTag.VENTING,
    "日常接话": OccasionTag.SMALLTALK,
    "口头禅": OccasionTag.SMALLTALK,
    "自称梗": OccasionTag.SELF_REFERENCE,
    "语气尾巴": OccasionTag.SENTENCE_TAIL,
    "日常问候": OccasionTag.GREETING,
    "感谢回应": OccasionTag.WARM_REPLY,
    "友好回应": OccasionTag.WARM_REPLY,
    "附和": OccasionTag.AGREEMENT,
}


def normalize_occasion_tag(value: str | OccasionTag) -> str:
    plain = str(value or "").strip()
    if not plain:
        return ""
    if plain in OccasionTag._value2member_map_:
        return plain
    if plain.startswith("吐槽"):
        return OccasionTag.VENTING
    if plain.startswith(("接梗", "玩笑")):
        return OccasionTag.BANTER
    if plain.startswith("安抚"):
        return OccasionTag.VENTING
    return _OCCASION_ALIASES.get(plain, plain).value if plain in _OCCASION_ALIASES else plain
