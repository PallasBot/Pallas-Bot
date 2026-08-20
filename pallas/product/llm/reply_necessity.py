"""接话必要性评分：决定是否值得抢话 / 进 LLM 补位。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

REPLY_NECESSITY_TRIGGER_SCORE = 50
# 无 reply cue 时，低于此分不抢话（避免仅靠 back_forth+pool 刷到 25~30）
REPLY_NECESSITY_NO_CUE_FLOOR = 45

_CQ_AT_RE = re.compile(r"\[CQ:at,qq=(\d+)\]", re.IGNORECASE)
_URL_RE = re.compile(r"(https?://|www\.|b23\.tv|t\.cn/)", re.IGNORECASE)
_EMOJI_ONLY_RE = re.compile(
    r"^[\s\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\U0000200D❤️🧡💛💚💙💜🖤🤍🤎💢]+$",
    re.UNICODE,
)
_DIRECT_REQUEST_TERMS = ("帮我", "帮忙", "能不能", "可以吗", "要不要")
_REPLY_OBLIGATION_RE = re.compile(
    r"[?？]|(?:怎么|如何|为什么|为啥|吗|么|能不能|可以吗|帮我|回我|快回|谁|什么|哪里|哪儿|哪|咋|"
    r"怎样|多少|几|有没有|要不要|会不会|是不是|能否|继续|再说|刚才|等等|等下|补一句|先别)"
)
_SPAM_PROMO_TERMS = (
    "点击即玩",
    "不用下载",
    "加我微信",
    "免费领",
    "引流",
    "扩列加",
    "无聊妹子",
    "陪聊",
)
_INCOMPLETE_UTTERANCES = frozenset({"你是", "我是", "那你", "然后", "所以", "因为"})
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
_NOISE_RE = re.compile(r"^[\W_\d]{1,6}$", re.UNICODE)
_SHORT_VENT_RE = re.compile(r"(?:烦|唉|累|难受|没绷住|服了|崩溃)[，,。.!！?？~～\s]*$")


@dataclass(frozen=True, slots=True)
class ReplyNecessityScore:
    score: int
    detail: str


ReplyNecessityGateDecision = Literal["proceed", "skip"]


@dataclass(frozen=True, slots=True)
class ReplyNecessityGateResult:
    decision: ReplyNecessityGateDecision
    score: int
    detail: str


def is_short_vent(text: str) -> bool:
    plain = str(text or "").strip()
    return len(plain) <= 24 and bool(_SHORT_VENT_RE.search(plain))


def is_low_value_social_turn(text: str) -> bool:
    plain = str(text or "").strip()
    return bool(plain) and len(plain) <= 24 and not has_reply_obligation(plain)


def has_reply_obligation(text: str) -> bool:
    return bool(_REPLY_OBLIGATION_RE.search(str(text or "").strip()))


def is_noise_fragment(text: str) -> bool:
    plain = str(text or "").strip()
    if not plain:
        return True
    if len(plain) == 1 and not ("\u4e00" <= plain <= "\u9fff"):
        return True
    if plain in _SHORT_REACTIONS and len(plain) <= 1:
        return True
    if _EMOJI_ONLY_RE.fullmatch(plain):
        return True
    if _NOISE_RE.fullmatch(plain):
        return True
    return False


def looks_like_spam_or_promo(text: str) -> bool:
    plain = str(text or "").strip()
    if not plain:
        return False
    if _URL_RE.search(plain) and len(plain) >= 24:
        return True
    return any(term in plain for term in _SPAM_PROMO_TERMS)


def is_incomplete_utterance(text: str) -> bool:
    plain = str(text or "").strip()
    if not plain:
        return False
    if plain in _INCOMPLETE_UTTERANCES:
        return True
    if len(plain) <= 3 and plain.endswith(("是", "的", "了")) and "?" not in plain and "？" not in plain:
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
    is_mentioned: bool = False,
    is_followup: bool = False,
    recent_bot_reply_count: int = 0,
    user_affinity: float | None = None,
    affinity_silence_threshold: float = -0.3,
    affinity_silence_max_penalty: int = 30,
) -> ReplyNecessityScore:
    plain = str(text or "").strip()
    score = 0
    parts: list[str] = []

    if is_to_me:
        score += 55
        parts.append("to_me+55")
    if is_mentioned:
        score += 35
        parts.append("mention+35")
    if is_followup:
        score += 25
        parts.append("followup+25")
    if is_bystander_plain_text(plain, bot_id=bot_id) and not is_to_me:
        score -= 45
        parts.append("bystander-45")
    if is_noise_fragment(plain):
        score -= 40
        parts.append("noise-40")
    if looks_like_spam_or_promo(plain):
        score -= 50
        parts.append("spam-50")
    if is_incomplete_utterance(plain) and not is_to_me:
        score -= 20
        parts.append("incomplete-20")
    if plain in _SHORT_REACTIONS:
        score -= 25
        parts.append("short_reaction-25")
    if any(term in plain for term in _DIRECT_REQUEST_TERMS):
        score += 25
        parts.append("request+25")
    if has_reply_obligation(plain):
        score += 20
        parts.append("obligation+20")
    if is_low_value_social_turn(plain) and not (is_mentioned or is_followup):
        score -= 35
        parts.append("low_social-35")
    if has_recent_back_and_forth:
        score += 15
        parts.append("back_forth+15")
    if has_candidate_pool:
        score += 10
        parts.append("pool+10")
    recent_presence = max(0, min(6, int(recent_bot_reply_count)))
    if recent_presence:
        if (is_to_me or is_mentioned or is_followup) and has_reply_obligation(plain):
            parts.append("bot_presence_exempt")
        else:
            penalty = recent_presence * 8
            score -= penalty
            parts.append(f"bot_presence-{penalty}")
    elif bot_recently_replied and not is_to_me:
        score -= 20
        parts.append("bot_recent-20")
    if 2 <= len(plain) <= 24:
        score += 5
        parts.append("len_ok+5")
    if (
        user_affinity is not None
        and user_affinity < affinity_silence_threshold
        and not (is_to_me or is_mentioned or is_followup)
    ):
        ratio = (affinity_silence_threshold - user_affinity) / (1.0 + affinity_silence_threshold)
        penalty = int(round(max(0.0, min(1.0, ratio)) * float(affinity_silence_max_penalty)))
        if penalty > 0:
            score -= penalty
            parts.append(f"affinity-{penalty}")

    return ReplyNecessityScore(score=score, detail=",".join(parts) or "base")


def evaluate_reply_necessity_gate(
    *,
    text: str,
    is_to_me: bool = False,
    bot_id: int | None = None,
    bot_recently_replied: bool = False,
    has_recent_back_and_forth: bool = False,
    has_candidate_pool: bool = False,
    is_mentioned: bool = False,
    is_followup: bool = False,
    recent_bot_reply_count: int = 0,
    threshold: int = REPLY_NECESSITY_TRIGGER_SCORE,
    user_affinity: float | None = None,
    affinity_silence_threshold: float = -0.3,
    affinity_silence_max_penalty: int = 30,
) -> ReplyNecessityGateResult:
    scored = score_reply_necessity(
        text=text,
        is_to_me=is_to_me,
        bot_id=bot_id,
        bot_recently_replied=bot_recently_replied,
        has_recent_back_and_forth=has_recent_back_and_forth,
        has_candidate_pool=has_candidate_pool,
        is_mentioned=is_mentioned,
        is_followup=is_followup,
        recent_bot_reply_count=recent_bot_reply_count,
        user_affinity=user_affinity,
        affinity_silence_threshold=affinity_silence_threshold,
        affinity_silence_max_penalty=affinity_silence_max_penalty,
    )
    decision: ReplyNecessityGateDecision = "proceed" if scored.score >= int(threshold) else "skip"
    return ReplyNecessityGateResult(decision=decision, score=scored.score, detail=scored.detail)
