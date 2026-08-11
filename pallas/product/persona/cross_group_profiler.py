from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any

from .group_expression_profile import GroupExpressionProfile
from .group_profiler import DEFAULT_WINDOW_HOURS

MIN_GROUP_COUNT = 2
MIN_TOTAL_WEIGHT = 15.0
MAX_GROUP_WEIGHT = 50.0
_WEIGHT_HALF_LIFE_HOURS = 168


def group_style_weight(style_profile: dict[str, Any], *, now_ts: int) -> float:
    profile = GroupExpressionProfile.from_style_profile(style_profile)
    aggregate = profile.aggregate
    answer_count = max(0, int(aggregate.answer_count))
    message_count = max(0, int(aggregate.message_count))
    if answer_count <= 0 or message_count <= 0:
        return 0.0

    sample_weight = math.sqrt(float(answer_count)) * math.sqrt(float(message_count))
    sample_weight = min(sample_weight, MAX_GROUP_WEIGHT)

    teach_weight = float(aggregate.forced_teach_weight)
    if teach_weight > 0:
        sample_weight *= 1.0 + min(0.5, teach_weight * 0.08)

    skip_total = int(aggregate.contamination_skipped_messages) + int(aggregate.contamination_skipped_answers)
    if skip_total > 0:
        kept_total = max(1, message_count + answer_count)
        ratio = skip_total / (kept_total + skip_total)
        if ratio >= 0.2:
            sample_weight *= max(0.2, 1.0 - ratio)

    updated_at = profile.updated_at.timestamp()
    age_hours = max(0.0, (int(now_ts) - updated_at) / 3600.0)
    decay = 0.5 ** (age_hours / float(_WEIGHT_HALF_LIFE_HOURS))

    return sample_weight * decay


def build_bot_cross_group_persona(
    *,
    bot_id: int,
    group_profiles: list[tuple[int, dict[str, Any]]],
    now_ts: int | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> dict[str, Any]:
    """汇总账号所在群的结构化表达画像，不生成账号人格覆盖。"""
    now = int(now_ts or time.time())
    weighted: list[tuple[float, GroupExpressionProfile]] = []

    for _gid, profile in group_profiles:
        if not isinstance(profile, dict):
            continue
        weight = group_style_weight(profile, now_ts=now)
        if weight <= 0:
            continue
        weighted.append((weight, GroupExpressionProfile.from_style_profile(profile)))

    total_weight = sum(w for w, _ in weighted)
    profile: dict[str, Any] = {
        "version": 1,
        "source": "cross_group_expression",
        "updated_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
        "aggregate": {
            "sample_count": sum(item.aggregate.sample_count for _, item in weighted),
            "window_hours": int(window_hours),
            "message_count": sum(item.aggregate.message_count for _, item in weighted),
            "answer_count": sum(item.aggregate.answer_count for _, item in weighted),
            "distinct_answer_keywords": sum(item.aggregate.distinct_answer_keywords for _, item in weighted),
            "active_hour_count": sum(item.aggregate.active_hour_count for _, item in weighted),
            "contamination_skipped_messages": sum(
                item.aggregate.contamination_skipped_messages for _, item in weighted
            ),
            "contamination_skipped_answers": sum(item.aggregate.contamination_skipped_answers for _, item in weighted),
        },
        "reply_shape": {"length_pref": "any"},
        "summary": {
            "window_hours": int(window_hours),
            "bot_id": int(bot_id),
            "group_count": len(weighted),
            "total_weight": round(total_weight, 3),
        },
    }

    if len(weighted) < MIN_GROUP_COUNT or total_weight < MIN_TOTAL_WEIGHT:
        return profile

    shape_weights: dict[str, float] = {}
    for weight, item in weighted:
        key = item.reply_shape.length_pref
        shape_weights[key] = shape_weights.get(key, 0.0) + weight
    profile["reply_shape"]["length_pref"] = max(shape_weights, key=shape_weights.get)
    return profile
