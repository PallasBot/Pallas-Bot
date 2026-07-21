"""接话必要性评分：决定是否值得抢话 / 进 LLM 补位。"""

from __future__ import annotations

import re
from dataclasses import dataclass

REPLY_NECESSITY_TRIGGER_SCORE = 50

_CQ_AT_RE = re.compile(r"\[CQ:at,qq=(\d+)\]", re.IGNORECASE)
_DIRECT_REQUEST_TERMS = ("帮我", "帮忙", "能不能", "可以吗", "要不要")
_QUESTION_TERMS = ("怎么", "如何", "为什么", "有没有", "咋")
_SHORT_REACTIONS = frozenset({
    "哈哈",
    "哈哈哈",
    "草",
    "笑死",
    "好",
    "嗯",
    "啊",
    "哦",
    "6",
    "666",
    "？",
    "?",
    "！",
    "!",
})
_NOISE_RE = re.compile(r"^[\W_\d]{1,3}$", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ReplyNecessityScore:
    score: int
    detail: str


def is_noise_fragment(text: str) -> bool:
    plain = str(text or "").strip()
    if not plain:
        return True
    if len(plain) == 1 and not ("\u4e00" <= plain <= "\u9fff"):
        return True
    if plain in _SHORT_REACTIONS and len(plain) <= 1:
        return True
    if _NOISE_RE.fullmatch(plain):
        return True
    return False


def is_bystander_plain_text(text: str, *, bot_id: int | None = None) -> bool:
    """消息 @ 了别人且未 @ 本 bot 时视为旁观者位。"""
    plain = str(text or "")
    at_ids = [int(match.group(1)) for match in _CQ_AT_RE.finditer(plain)]
    if not at_ids:
        return False
    if bot_id is None:
        return True
    bot = int(bot_id)
    return bot not in at_ids


def score_reply_necessity(
    *,
    text: str,
    is_to_me: bool = False,
    bot_id: int | None = None,
    bot_recently_replied: bool = False,
    has_recent_back_and_forth: bool = False,
    has_candidate_pool: bool = False,
) -> ReplyNecessityScore:
    plain = str(text or "").strip()
    score = 0
    parts: list[str] = []

    if is_to_me:
        score += 55
        parts.append("to_me+55")
    if is_bystander_plain_text(plain, bot_id=bot_id) and not is_to_me:
        score -= 45
        parts.append("bystander-45")
    if is_noise_fragment(plain):
        score -= 40
        parts.append("noise-40")
    if plain in _SHORT_REACTIONS:
        score -= 25
        parts.append("short_reaction-25")
    if any(term in plain for term in _DIRECT_REQUEST_TERMS):
        score += 25
        parts.append("request+25")
    if any(term in plain for term in _QUESTION_TERMS) or "?" in plain or "？" in plain:
        score += 20
        parts.append("question+20")
    if has_recent_back_and_forth:
        score += 15
        parts.append("back_forth+15")
    if has_candidate_pool:
        score += 10
        parts.append("pool+10")
    if bot_recently_replied and not is_to_me:
        score -= 20
        parts.append("bot_recent-20")
    if 2 <= len(plain) <= 24:
        score += 5
        parts.append("len_ok+5")

    return ReplyNecessityScore(score=score, detail=",".join(parts) or "base")
