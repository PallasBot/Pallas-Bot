from __future__ import annotations

import statistics
import time
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from .group_expression_profile import (
    MIN_READY_ANSWER_COUNT,
    MIN_READY_MESSAGE_COUNT,
    GroupExpressionAggregate,
    GroupExpressionProfile,
    GroupReplyShapeHint,
    MessageLengthDistribution,
)

if TYPE_CHECKING:
    from pallas.core.foundation.db.modules import Answer, Message

from pallas.product.llm.sender_identity import is_peer_bot

DEFAULT_WINDOW_HOURS = 168
MIN_MESSAGE_COUNT = MIN_READY_MESSAGE_COUNT
MIN_ANSWER_COUNT = MIN_READY_ANSWER_COUNT

# 取数分页上限：每页 32 行（repo 内部 cap），多 bot 并发旁路记录会让同一消息
# 以不同 bot_id 落多行，单窗口极易被牛牛状态消息占满，故分页回溯后按 message_id 去重。
_PROFILE_PAGE_LIMIT = 12


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


def _segment_lengths(plain_text: str) -> list[int]:
    """按换行把一条消息拆成若干段，返回各段字符长度（与语义层分段口径一致）。"""
    segments = [item.strip() for item in str(plain_text or "").splitlines() if item.strip()]
    if not segments and str(plain_text or "").strip():
        segments = [str(plain_text or "").strip()]
    return [len(item) for item in segments]


def build_group_style_profile(
    *,
    group_id: int,
    messages: list[Message],
    answers: list[Answer],
    now_ts: int | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    forced_teach_weight: float = 0.0,
) -> dict[str, Any]:
    now = int(now_ts or time.time())
    cutoff = now - int(window_hours) * 3600

    recent_messages = [m for m in messages if int(getattr(m, "group_id", 0)) == int(group_id) and int(m.time) >= cutoff]
    recent_answers = [a for a in answers if int(getattr(a, "group_id", 0)) == int(group_id) and int(a.time) >= cutoff]

    from pallas.product.llm.corpus_contamination import is_profiler_answer_safe, is_profiler_sample_safe

    message_skipped_contamination = 0
    filtered_messages: list[Message] = []
    for message in recent_messages:
        plain = str(getattr(message, "plain_text", "") or "").strip()
        if plain and not is_profiler_sample_safe(plain):
            message_skipped_contamination += 1
            continue
        user_id = int(getattr(message, "user_id", 0) or 0)
        if user_id and (user_id == int(getattr(message, "bot_id", 0) or 0) or is_peer_bot(user_id)):
            continue
        filtered_messages.append(message)

    answer_skipped_contamination = 0
    filtered_answers: list[Answer] = []
    for answer in recent_answers:
        if not is_profiler_answer_safe(answer):
            answer_skipped_contamination += 1
            continue
        filtered_answers.append(answer)

    recent_messages = filtered_messages
    recent_answers = filtered_answers

    plain_lengths = sorted(
        len(str(getattr(m, "plain_text", "") or "").strip())
        for m in recent_messages
        if str(getattr(m, "plain_text", "") or "").strip()
    )
    non_empty_plain_lengths = [n for n in plain_lengths if n > 0]
    avg_plain_len = round(statistics.fmean(non_empty_plain_lengths), 2) if non_empty_plain_lengths else 0.0
    p50_plain_len = _quantile(non_empty_plain_lengths, 0.5)
    p90_plain_len = _quantile(non_empty_plain_lengths, 0.9)

    bubble_counts = []
    for message in recent_messages:
        segment_lengths = _segment_lengths(str(getattr(message, "plain_text", "") or ""))
        if segment_lengths:
            bubble_counts.append(len(segment_lengths))
    segment_lengths_flat = sorted(
        length
        for message in recent_messages
        for length in _segment_lengths(str(getattr(message, "plain_text", "") or ""))
        if length > 0
    )

    rhythm_counts: dict[str, int] = {
        "single": sum(1 for count in bubble_counts if count == 1),
        "multi": sum(1 for count in bubble_counts if count > 1),
    }

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

    keyword_counts = Counter(str(answer.keywords) for answer in recent_answers if str(answer.keywords or "").strip())
    repeated_answer_entries = sum(1 for answer in recent_answers if int(getattr(answer, "count", 0) or 0) >= 2)
    repeated_keywords = sum(1 for count in keyword_counts.values() if count >= 2)
    repeat_chain_rate = 0.0
    if answer_count:
        repeat_chain_rate = round(
            _clamp(
                (repeated_answer_entries + repeated_keywords) / (answer_count * 2),
                0.0,
                1.0,
            ),
            4,
        )

    profile = GroupExpressionProfile(
        aggregate=GroupExpressionAggregate(
            sample_count=message_count + answer_count,
            window_hours=int(window_hours),
            message_count=message_count,
            answer_count=answer_count,
            distinct_answer_keywords=distinct_answer_keywords,
            active_hour_count=len(hour_buckets),
            messages_per_active_hour=msgs_per_hour_active,
            message_length=MessageLengthDistribution(
                average=avg_plain_len,
                p50=p50_plain_len,
                p90=p90_plain_len,
            ),
            answer_ratio=local_answer_ratio,
            repetition_rate=repeat_chain_rate,
            forced_teach_weight=round(max(0.0, float(forced_teach_weight)), 3),
            contamination_skipped_messages=message_skipped_contamination,
            contamination_skipped_answers=answer_skipped_contamination,
        ),
        reply_shape=GroupReplyShapeHint(
            length_pref=_length_pref(p50_plain_len, p90_plain_len)
            if message_count >= MIN_MESSAGE_COUNT and answer_count >= MIN_ANSWER_COUNT
            else "any",
            bubble_count_p50=_quantile(bubble_counts, 0.5),
            bubble_count_p90=_quantile(bubble_counts, 0.9),
            segment_char_length_p50=_quantile(segment_lengths_flat, 0.5),
            segment_char_length_p90=_quantile(segment_lengths_flat, 0.9),
            rhythm_distribution=(
                {name: round(count / sum(rhythm_counts.values()), 4) for name, count in rhythm_counts.items()}
                if sum(rhythm_counts.values())
                else {}
            ),
        ),
        updated_at=now,
    )
    return profile.model_dump(mode="json")


async def build_group_style_profile_from_recent_repos(
    *,
    group_id: int,
    message_repo,
    context_repo,
    now_ts: int | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    forced_teach_weight: float = 0.0,
) -> dict[str, Any]:
    now = int(now_ts or time.time())
    cutoff = now - int(window_hours) * 3600

    messages = await _load_recent_messages_deduped(message_repo, group_id, before_time=now + 1)
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
        forced_teach_weight=forced_teach_weight,
    )


async def _load_recent_messages_deduped(message_repo, group_id: int, *, before_time: int) -> list[Message]:
    """分页回溯取最近消息并按 message_id 去重。

    多 bot 并发旁路记录会让同一条消息以不同 ``bot_id`` 落多行（message_id 相同），
    单窗口 32 行极易被这类重复行塞满，导致真人消息被挤出统计窗口。这里对齐
    群洞察取数的方式：分页向前回溯，跨页按 message_id 去重。
    """
    unique_map: dict[int, Message] = {}
    cursor = before_time
    for _ in range(_PROFILE_PAGE_LIMIT):
        batch = await message_repo.find_recent_in_group(int(group_id), before_time=cursor, limit=32)
        if not batch:
            break
        earliest = None
        for item in batch:
            mid = int(getattr(item, "message_id", 0) or 0)
            if mid <= 0:
                continue
            unique_map.setdefault(mid, item)
            ts = int(getattr(item, "time", 0) or 0)
            if earliest is None or ts < earliest:
                earliest = ts
        if earliest is None or earliest >= cursor:
            break
        # 同秒多条消息会因 time < cursor 严格小于被跳过（与群洞察取数同口径，可接受）。
        cursor = earliest
    return list(unique_map.values())
