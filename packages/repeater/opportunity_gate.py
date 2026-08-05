from __future__ import annotations

import random
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

_REPLY_CUE_TOKENS = (
    "?",
    "？",
    "!",
    "！",
    "吗",
    "呢",
    "吧",
    "真的假的",
    "真假的",
    "笑死",
    "离谱",
    "怎么个事",
)

SceneTier = Literal["strong", "weak"]


def looks_like_reply_cue(plain_text: str) -> bool:
    plain = str(plain_text or "").strip()
    if not plain:
        return False
    if any(token in plain for token in _REPLY_CUE_TOKENS):
        return True
    if 2 <= len(plain) <= 6 and plain.endswith(("确实", "离谱", "笑死")):
        return True
    if len(plain) <= 10 and plain.startswith(("这也", "这就", "怎么", "咋", "什么")):
        return True
    return False


def resolve_scene_tier(
    plain_text: str,
    *,
    candidate_pool_size: int,
    has_candidate_pool: bool,
    has_recent_back_and_forth: bool,
    is_to_me: bool,
) -> SceneTier:
    if bool(is_to_me):
        return "strong"
    if looks_like_reply_cue(plain_text) and bool(has_candidate_pool) and int(candidate_pool_size) >= 2:
        return "strong"
    if bool(has_recent_back_and_forth) and bool(has_candidate_pool):
        return "strong"
    return "weak"


def estimate_candidate_style_score(candidate_pool: list[str], *, reply_mode: str = "normal") -> float:
    samples = [str(item or "").strip() for item in candidate_pool if str(item or "").strip()]
    if not samples:
        return 0.0
    score = 0.0
    for text in samples[:4]:
        sample_score = 0.0
        if looks_like_reply_cue(text):
            sample_score += 0.45
        if 2 <= len(text) <= 12:
            sample_score += 0.25
        if any(token in text for token in ("草", "笑死", "离谱", "啊？", "？", "!", "！", "~")):
            sample_score += 0.2
        if reply_mode == "ghost" and len(text) <= 8:
            sample_score += 0.1
        if reply_mode == "god" and len(text) >= 12:
            sample_score = max(0.0, sample_score - 0.08)
        score = max(score, min(sample_score, 1.0))
    return round(score, 3)


def passes_repeater_hard_bars(
    plain_text: str,
    *,
    has_candidate_pool: bool,
    candidate_pool_size: int,
    has_recent_back_and_forth: bool,
    bot_recently_replied: bool,
    candidate_style_score: float = 0.0,
    reply_mode: str = "normal",
    is_to_me: bool = False,
    bot_id: int | None = None,
) -> bool:
    from pallas.product.llm.reply_necessity import (
        REPLY_NECESSITY_NO_CUE_FLOOR,
        is_bystander_plain_text,
        is_noise_fragment,
        looks_like_spam_or_promo,
        score_reply_necessity,
    )

    if is_to_me:
        return True

    plain = str(plain_text or "").strip()
    if not plain:
        return False
    if is_bystander_plain_text(plain, bot_id=bot_id):
        return False
    if looks_like_spam_or_promo(plain):
        return False

    has_reply_cue = looks_like_reply_cue(plain)
    cue_with_pool = bool(has_reply_cue and has_candidate_pool and candidate_pool_size >= 2)
    if is_noise_fragment(plain) and not cue_with_pool:
        return False

    necessity = score_reply_necessity(
        text=plain,
        is_to_me=False,
        bot_id=bot_id,
        bot_recently_replied=bot_recently_replied,
        has_recent_back_and_forth=has_recent_back_and_forth,
        has_candidate_pool=has_candidate_pool,
    )
    mode = str(reply_mode or "normal").strip().lower()
    has_strong_context = has_candidate_pool and candidate_pool_size >= 2 and has_recent_back_and_forth
    has_ghost_style = mode == "ghost" and has_candidate_pool and candidate_style_score >= 0.72
    if necessity.score < 0 and not has_reply_cue and not (has_strong_context or has_ghost_style):
        return False
    if not has_reply_cue and necessity.score < REPLY_NECESSITY_NO_CUE_FLOOR:
        if has_strong_context:
            return True
        return has_ghost_style
    return True


def should_attempt_repeater_opportunity(
    plain_text: str,
    *,
    unique_users: int,
    recent_message_count: int,
    has_candidate_pool: bool,
    candidate_pool_size: int,
    candidate_style_score: float,
    has_recent_back_and_forth: bool,
    bot_recently_replied: bool,
    reply_mode: str = "normal",
    is_to_me: bool = False,
    bot_id: int | None = None,
    scene_tier: SceneTier | None = None,
) -> bool:
    plain = str(plain_text or "").strip()
    mode = str(reply_mode or "normal").strip().lower()
    if not passes_repeater_hard_bars(
        plain,
        has_candidate_pool=has_candidate_pool,
        candidate_pool_size=candidate_pool_size,
        has_recent_back_and_forth=has_recent_back_and_forth,
        bot_recently_replied=bot_recently_replied,
        candidate_style_score=candidate_style_score,
        reply_mode=mode,
        is_to_me=is_to_me,
        bot_id=bot_id,
    ):
        return False
    if is_to_me:
        return True
    if scene_tier == "strong":
        return unique_users >= 2 and recent_message_count >= 2

    has_reply_cue = looks_like_reply_cue(plain)
    cue_with_pool = bool(has_reply_cue and has_candidate_pool and candidate_pool_size >= 2)
    if unique_users < 2:
        return False
    # cue + 候选池：略放宽活跃度门槛（仍至少 2 条近期消息）
    if recent_message_count < 3 and not (cue_with_pool and recent_message_count >= 2):
        return False
    has_strong_pool = has_candidate_pool and candidate_pool_size >= 2
    if mode == "ghost":
        has_strong_pool = has_strong_pool or candidate_style_score >= 0.72
    elif mode == "god":
        has_strong_pool = has_strong_pool and candidate_style_score >= 0.6
    else:
        has_strong_pool = has_strong_pool or candidate_style_score >= 0.82
    if not has_candidate_pool and len(plain) < 4:
        return has_recent_back_and_forth and has_reply_cue
    if not has_candidate_pool and not (has_recent_back_and_forth and has_reply_cue):
        return False
    if bot_recently_replied and not (has_recent_back_and_forth and has_reply_cue) and not cue_with_pool:
        return False
    if mode == "normal" and not has_recent_back_and_forth and not has_strong_pool:
        return False
    if not (has_recent_back_and_forth or has_strong_pool or has_reply_cue):
        return False
    return True


def decide_llm_attempt(
    *,
    scene_tier: str,
    opportunity_accepted: bool,
    strong_attempt_rate: float,
    rng: Callable[[], float] | None = None,
) -> tuple[bool, float | None, str | None]:
    if not opportunity_accepted:
        return False, None, "opportunity_rejected"
    if str(scene_tier).strip().lower() != "strong":
        return True, None, None
    roll = (rng or random.random)()
    if roll >= float(strong_attempt_rate):
        return False, roll, "rate"
    return True, roll, None


def build_opportunity_trace_payload(
    plain_text: str,
    *,
    unique_users: int,
    recent_message_count: int,
    has_candidate_pool: bool,
    candidate_pool_size: int,
    candidate_style_score: float,
    has_recent_back_and_forth: bool,
    bot_recently_replied: bool,
    reply_mode: str = "normal",
    is_to_me: bool = False,
    accepted: bool,
    bot_id: int | None = None,
) -> dict[str, object]:
    from pallas.product.llm.reply_necessity import is_bystander_plain_text, score_reply_necessity

    plain = str(plain_text or "").strip()
    mode = str(reply_mode or "normal").strip().lower()
    necessity = score_reply_necessity(
        text=plain,
        is_to_me=is_to_me,
        bot_id=bot_id,
        bot_recently_replied=bot_recently_replied,
        has_recent_back_and_forth=has_recent_back_and_forth,
        has_candidate_pool=has_candidate_pool,
    )
    return {
        "kind": "llm_opportunity_gate",
        "reply_mode": mode or "normal",
        "accepted": bool(accepted),
        "plain_preview": plain[:80],
        "plain_len": len(plain),
        "is_to_me": bool(is_to_me),
        "unique_users": int(unique_users),
        "recent_message_count": int(recent_message_count),
        "has_candidate_pool": bool(has_candidate_pool),
        "candidate_pool_size": int(candidate_pool_size),
        "candidate_style_score": float(candidate_style_score),
        "has_recent_back_and_forth": bool(has_recent_back_and_forth),
        "bot_recently_replied": bool(bot_recently_replied),
        "scene_tier": resolve_scene_tier(
            plain,
            candidate_pool_size=candidate_pool_size,
            has_candidate_pool=has_candidate_pool,
            has_recent_back_and_forth=has_recent_back_and_forth,
            is_to_me=is_to_me,
        ),
        "has_reply_cue": bool(looks_like_reply_cue(plain)),
        "cue_with_pool": bool(looks_like_reply_cue(plain) and has_candidate_pool and candidate_pool_size >= 2),
        "bystander": bool(is_bystander_plain_text(plain, bot_id=bot_id)),
        "necessity_score": int(necessity.score),
        "necessity_detail": necessity.detail,
    }
