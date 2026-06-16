from __future__ import annotations

import statistics
import time
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.foundation.db.modules import Answer, Message


DEFAULT_WINDOW_HOURS = 168
MIN_MESSAGE_COUNT = 30
MIN_ANSWER_COUNT = 5


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _quantile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return int(sorted_values[0])
    idx = round((len(sorted_values) - 1) * q)
    return int(sorted_values[idx])


def _length_pref(p50_plain_len: int, p90_plain_len: int) -> str:
    if p50_plain_len <= 12 and p90_plain_len <= 24:
        return "short"
    if p50_plain_len >= 20 or p90_plain_len >= 36:
        return "long"
    return "medium"


def build_group_style_profile(
    *,
    group_id: int,
    messages: list[Message],
    answers: list[Answer],
    now_ts: int | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> dict[str, Any]:
    now = int(now_ts or time.time())
    cutoff = now - int(window_hours) * 3600

    recent_messages = [m for m in messages if int(getattr(m, "group_id", 0)) == int(group_id) and int(m.time) >= cutoff]
    recent_answers = [a for a in answers if int(getattr(a, "group_id", 0)) == int(group_id) and int(a.time) >= cutoff]

    plain_lengths = sorted(
        len(str(getattr(m, "plain_text", "") or "").strip())
        for m in recent_messages
        if str(getattr(m, "plain_text", "") or "").strip()
    )
    non_empty_plain_lengths = [n for n in plain_lengths if n > 0]
    avg_plain_len = round(statistics.fmean(non_empty_plain_lengths), 2) if non_empty_plain_lengths else 0.0
    p50_plain_len = _quantile(non_empty_plain_lengths, 0.5)
    p90_plain_len = _quantile(non_empty_plain_lengths, 0.9)

    hour_buckets: dict[int, int] = defaultdict(int)
    for message in recent_messages:
        hour_buckets[int(message.time) // 3600] += 1
    msgs_per_hour_active = round(statistics.fmean(hour_buckets.values()), 2) if hour_buckets else 0.0

    answer_count = len(recent_answers)
    message_count = len(recent_messages)
    distinct_answer_keywords = len({
        str(answer.keywords) for answer in recent_answers if str(answer.keywords or "").strip()
    })
    local_answer_ratio = round(answer_count / message_count, 4) if message_count else 0.0

    short_message_count = sum(1 for n in non_empty_plain_lengths if n <= 4)
    short_message_ratio = short_message_count / message_count if message_count else 0.0
    keyword_counts = Counter(str(answer.keywords) for answer in recent_answers if str(answer.keywords or "").strip())
    repeated_answer_entries = sum(1 for answer in recent_answers if int(getattr(answer, "count", 0) or 0) >= 2)
    repeated_keywords = sum(1 for count in keyword_counts.values() if count >= 2)
    repeat_chain_rate = 0.0
    if answer_count:
        repeat_chain_rate = round(
            _clamp(
                (repeated_answer_entries + repeated_keywords + short_message_ratio * answer_count) / (answer_count * 3),
                0.0,
                1.0,
            ),
            4,
        )

    profile: dict[str, Any] = {
        "version": 1,
        "updated_at": now,
        "sample": {
            "window_hours": int(window_hours),
            "message_count": message_count,
            "answer_count": answer_count,
            "distinct_answer_keywords": distinct_answer_keywords,
        },
        "raw": {
            "avg_plain_len": avg_plain_len,
            "p50_plain_len": p50_plain_len,
            "p90_plain_len": p90_plain_len,
            "msgs_per_hour_active": msgs_per_hour_active,
            "local_answer_ratio": local_answer_ratio,
            "repeat_chain_rate": repeat_chain_rate,
        },
    }

    if message_count < MIN_MESSAGE_COUNT or answer_count < MIN_ANSWER_COUNT:
        return profile

    answer_diversity = distinct_answer_keywords / answer_count if answer_count else 0.0
    reply_bias_mul = _clamp(0.92 + local_answer_ratio * 0.35 + min(msgs_per_hour_active, 12.0) * 0.01, 0.85, 1.15)
    speak_bias_mul = _clamp(0.95 + min(msgs_per_hour_active, 10.0) * 0.008 + repeat_chain_rate * 0.08, 0.9, 1.1)
    chaos_bias = _clamp(
        repeat_chain_rate * 0.45 + short_message_ratio * 0.15 + max(0.0, (1.0 - answer_diversity)) * 0.05, 0.0, 0.25
    )

    profile["derived"] = {
        "reply_bias_mul": round(reply_bias_mul, 3),
        "speak_bias_mul": round(speak_bias_mul, 3),
        "length_pref": _length_pref(p50_plain_len, p90_plain_len),
        "chaos_bias": round(chaos_bias, 3),
    }
    return profile


async def build_group_style_profile_from_recent_repos(
    *,
    group_id: int,
    message_repo,
    context_repo,
    now_ts: int | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> dict[str, Any]:
    now = int(now_ts or time.time())
    cutoff = now - int(window_hours) * 3600

    messages = await message_repo.find_recent_in_group(int(group_id), before_time=now + 1, limit=32)
    list_answers = getattr(context_repo, "list_answers_for_group_since", None)
    if callable(list_answers):
        answers = await list_answers(int(group_id), int(cutoff))
    else:
        answers = []

    return build_group_style_profile(
        group_id=int(group_id),
        messages=list(messages),
        answers=list(answers),
        now_ts=now,
        window_hours=window_hours,
    )
