import re
from typing import Any

from .model import ResolvedPersona

_LOW_INFO_RE = re.compile(r"^[\W_]+$", re.UNICODE)


def scaled_answer_threshold(base_threshold: int, persona: ResolvedPersona, *, in_hosted_activity: bool) -> int:
    """reply_bias 越高越容易接话（有效阈值越低）；warmth 略放大 reply_bias。"""
    bias = persona.reply_bias * (1.0 + max(-0.5, min(0.5, persona.warmth)) * 0.12)
    if in_hosted_activity:
        bias *= persona.activity_reply_bias
    if bias <= 0:
        return base_threshold
    scaled = int(round(base_threshold / bias))
    return max(1, scaled)


def scaled_speak_threshold(base_threshold: int, persona: ResolvedPersona) -> float:
    if persona.speak_bias <= 0:
        return float(base_threshold)
    return base_threshold / persona.speak_bias


def chaos_message_multiplier(text: str, persona: ResolvedPersona) -> float:
    """chaos 越高越偏短句、口语碎片。"""
    chaos = float(persona.chaos_bias)
    if chaos <= 0:
        return 1.0
    plain = (text or "").strip()
    n = len(plain)
    if n <= 8:
        return 1.0 + chaos * 0.8
    if n <= 15:
        return 1.0 + chaos * 0.35
    if n >= 40:
        return max(0.55, 1.0 - chaos * 0.5)
    return 1.0


def answer_popularity_multiplier(count: int, persona: ResolvedPersona) -> float:
    """chaos 越高越偏高频 answer；assertiveness 高时略偏冷门句。"""
    popularity = min(max(int(count), 0), 10) / 10.0
    chaos = float(persona.chaos_bias)
    if chaos >= 0.05:
        mul = 1.0 + chaos * popularity * 0.6
    else:
        mul = 1.0 + (1.0 - popularity) * 0.12
    if persona.assertiveness >= 0.12:
        mul *= 1.0 + persona.assertiveness * (1.0 - popularity) * 0.25
    elif persona.assertiveness <= -0.12:
        mul *= 1.0 + abs(persona.assertiveness) * popularity * 0.15
    return mul


def message_weight_multiplier(text: str, persona: ResolvedPersona) -> float:
    plain = (text or "").strip()
    if not plain:
        return 0.1

    weight = 1.0
    n = len(plain)

    if persona.length_pref == "short":
        weight *= 1.35 if n <= 15 else 0.55
    elif persona.length_pref == "long":
        weight *= 1.35 if n >= 30 else 0.65
    elif persona.length_pref == "medium":
        weight *= 1.2 if 15 < n < 30 else 0.85

    if persona.tone == "terse":
        weight *= 1.25 if n <= 12 else 0.7
    elif persona.tone == "dramatic":
        weight *= 1.15 if n >= 20 or "！" in plain or "!" in plain else 0.9
    elif persona.tone == "enthusiastic":
        weight *= 1.1 if ("？" in plain or "?" in plain or "！" in plain or "!" in plain) else 1.0
    elif persona.tone == "calm":
        weight *= 1.05 if n <= 18 else 0.95

    weight *= low_info_multiplier(plain)
    weight *= chaos_message_multiplier(plain, persona)
    return max(0.05, weight)


def freshness_multiplier(text: str, recent_sent: list[str], *, persona: ResolvedPersona | None = None) -> float:
    if text not in recent_sent:
        return 1.0
    penalty = 0.3
    if persona is not None and persona.chaos_bias > 0:
        penalty = min(0.85, 0.3 + float(persona.chaos_bias) * 0.55)
    return penalty


def speak_message_weight(text: str, persona: ResolvedPersona, *, recent_speaks: list[str]) -> float:
    plain = (text or "").strip()
    if not plain:
        return 0.05
    return max(
        0.05,
        message_weight_multiplier(plain, persona) * freshness_multiplier(plain, recent_speaks, persona=persona),
    )


def speak_keyword_group_weight(
    messages: list[Any],
    persona: ResolvedPersona,
    *,
    recent_speaks: list[str],
) -> float:
    """主动发言选 topic：同 keywords 消息越多越热门；chaos 高时进一步偏热门。"""
    if not messages:
        return 0.05
    topic_count = len(messages)
    base = min(topic_count, 10) * answer_popularity_multiplier(topic_count, persona)
    mults = [
        speak_message_weight(
            str(getattr(msg, "plain_text", None) or getattr(msg, "raw_message", "") or ""),
            persona,
            recent_speaks=recent_speaks,
        )
        for msg in messages
    ]
    return max(0.05, base * max(mults))


def low_info_multiplier(text: str) -> float:
    plain = (text or "").strip()
    if not plain:
        return 0.1
    if len(plain) == 1 and not plain.isalnum():
        return 0.2
    if _LOW_INFO_RE.fullmatch(plain):
        return 0.2
    return 1.0
