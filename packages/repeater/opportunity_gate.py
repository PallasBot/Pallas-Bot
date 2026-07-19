from __future__ import annotations

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
) -> bool:
    plain = str(plain_text or "").strip()
    mode = str(reply_mode or "normal").strip().lower()
    if is_to_me:
        return True
    if not plain:
        return False
    if unique_users < 2:
        return False
    has_reply_cue = looks_like_reply_cue(plain)
    cue_with_pool = bool(has_reply_cue and has_candidate_pool and candidate_pool_size >= 2)
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
) -> dict[str, object]:
    plain = str(plain_text or "").strip()
    mode = str(reply_mode or "normal").strip().lower()
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
        "has_reply_cue": bool(looks_like_reply_cue(plain)),
        "cue_with_pool": bool(looks_like_reply_cue(plain) and has_candidate_pool and candidate_pool_size >= 2),
    }
