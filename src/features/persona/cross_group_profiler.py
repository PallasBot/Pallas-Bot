from __future__ import annotations

import math
import time
from typing import Any

from .group_profiler import DEFAULT_WINDOW_HOURS

MIN_GROUP_COUNT = 2
MIN_TOTAL_WEIGHT = 15.0
MAX_GROUP_WEIGHT = 50.0
_WEIGHT_HALF_LIFE_HOURS = 168

_LENGTH_ORD: dict[str, float] = {"short": 0.0, "medium": 1.0, "long": 2.0}
_LENGTH_FROM_ORD: tuple[str, ...] = ("short", "medium", "long")


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def group_style_weight(style_profile: dict[str, Any], *, now_ts: int) -> float:
    derived = style_profile.get("derived")
    if not isinstance(derived, dict):
        return 0.0
    sample = style_profile.get("sample")
    if not isinstance(sample, dict):
        return 0.0

    answer_count = max(0, int(sample.get("answer_count") or 0))
    message_count = max(0, int(sample.get("message_count") or 0))
    if answer_count <= 0 or message_count <= 0:
        return 0.0

    sample_weight = math.sqrt(float(answer_count)) * math.sqrt(float(message_count))
    sample_weight = min(sample_weight, MAX_GROUP_WEIGHT)

    teach_weight = float(sample.get("forced_teach_weight") or 0.0)
    if teach_weight > 0:
        sample_weight *= 1.0 + min(0.5, teach_weight * 0.08)

    updated_at = int(style_profile.get("updated_at") or 0)
    if updated_at <= 0:
        decay = 1.0
    else:
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
    """将多头牛近期活跃群的 style_profile.derived 加权汇总为 bot_config.persona。"""
    now = int(now_ts or time.time())
    weighted: list[tuple[float, dict[str, Any]]] = []
    total_answer_count = 0

    for _gid, profile in group_profiles:
        if not isinstance(profile, dict):
            continue
        weight = group_style_weight(profile, now_ts=now)
        if weight <= 0:
            continue
        derived = profile.get("derived")
        if not isinstance(derived, dict):
            continue
        sample = profile.get("sample")
        if isinstance(sample, dict):
            total_answer_count += int(sample.get("answer_count") or 0)
        weighted.append((weight, derived))

    total_weight = sum(w for w, _ in weighted)
    profile: dict[str, Any] = {
        "version": 1,
        "source": "cross_group",
        "updated_at": now,
        "sample": {
            "window_hours": int(window_hours),
            "bot_id": int(bot_id),
            "group_count": len(weighted),
            "total_weight": round(total_weight, 3),
            "total_answer_count": total_answer_count,
        },
    }

    if len(weighted) < MIN_GROUP_COUNT or total_weight < MIN_TOTAL_WEIGHT:
        return profile

    reply_sum = 0.0
    speak_sum = 0.0
    chaos_sum = 0.0
    warmth_sum = 0.0
    assertiveness_sum = 0.0
    length_ord_sum = 0.0

    for weight, derived in weighted:
        reply_sum += weight * float(derived.get("reply_bias_mul") or 1.0)
        speak_sum += weight * float(derived.get("speak_bias_mul") or 1.0)
        chaos_sum += weight * float(derived.get("chaos_bias") or 0.0)
        warmth_sum += weight * float(derived.get("warmth_bias") or 0.0)
        assertiveness_sum += weight * float(derived.get("assertiveness_bias") or 0.0)
        length_key = str(derived.get("length_pref") or "medium").strip()
        length_ord_sum += weight * _LENGTH_ORD.get(length_key, 1.0)

    inv = 1.0 / total_weight
    length_ord = _clamp(round(length_ord_sum * inv), 0.0, 2.0)
    length_idx = int(length_ord + 0.5)

    profile["derived"] = {
        "reply_bias_mul": round(_clamp(reply_sum * inv, 0.85, 1.15), 3),
        "speak_bias_mul": round(_clamp(speak_sum * inv, 0.9, 1.1), 3),
        "length_pref": _LENGTH_FROM_ORD[length_idx],
        "chaos_bias": round(_clamp(chaos_sum * inv, 0.0, 0.25), 3),
        "warmth_bias": round(_clamp(warmth_sum * inv, -0.35, 0.35), 3),
        "assertiveness_bias": round(_clamp(assertiveness_sum * inv, -0.1, 0.4), 3),
    }
    return profile
