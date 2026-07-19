"""情感基线：统计推导 warmth / assertiveness，可选 LLM refine 钩子。"""

from __future__ import annotations

import time
from typing import Any

AFFECT_REFINE_SOURCE_NONE = "none"
AFFECT_REFINE_SOURCE_LLM = "llm"
AFFECT_REFINE_SOURCE_HEURISTIC = "heuristic"


def clamp_affect(value: float, *, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def derive_group_affect_bias(
    *,
    repeat_chain_rate: float,
    short_message_ratio: float,
    local_answer_ratio: float,
    forced_teach_weight: float = 0.0,
    civility_score: float = 0.0,
    harsh_msg_ratio: float = 0.0,
    polite_msg_ratio: float = 0.0,
    punct_aggression_avg: float = 0.0,
) -> dict[str, float]:
    """从群统计推导慢变情感偏移（无 LLM）。"""
    civility = clamp_affect(civility_score, lower=-1.0, upper=1.0)
    warmth_bias = clamp_affect(
        (local_answer_ratio - 0.15) * 0.5
        + (0.12 - repeat_chain_rate) * 0.35
        + civility * 0.18
        + polite_msg_ratio * 0.08,
        lower=-0.35,
        upper=0.35,
    )
    assertiveness_bias = clamp_affect(
        repeat_chain_rate * 0.4
        + short_message_ratio * 0.12
        + min(max(0.0, forced_teach_weight), 6.0) * 0.025
        + harsh_msg_ratio * 0.15
        + punct_aggression_avg * 0.12
        - civility * 0.1,
        lower=-0.05,
        upper=0.4,
    )
    return {
        "warmth_bias": round(warmth_bias, 3),
        "assertiveness_bias": round(assertiveness_bias, 3),
    }


def empty_affect_refine() -> dict[str, Any]:
    return {
        "source": AFFECT_REFINE_SOURCE_NONE,
        "warmth_delta": 0.0,
        "assertiveness_delta": 0.0,
        "confidence": 0.0,
        "summary": "",
        "updated_at": None,
    }


def heuristic_affect_refine_record(profile: dict[str, Any]) -> dict[str, Any]:
    """本地 civility 启发式，与 AI 仓回退逻辑对齐。"""
    raw = profile.get("raw") if isinstance(profile.get("raw"), dict) else {}
    tone = raw.get("affect_tone") if isinstance(raw.get("affect_tone"), dict) else {}
    civility = float(tone.get("civility_score") or 0.0)
    warmth_delta = round(clamp_affect(civility * 0.05, lower=-0.5, upper=0.5), 3)
    assertiveness_delta = round(clamp_affect(-civility * 0.04, lower=-0.5, upper=0.5), 3)
    if abs(warmth_delta) < 0.01 and abs(assertiveness_delta) < 0.01:
        return empty_affect_refine()
    return {
        "source": AFFECT_REFINE_SOURCE_HEURISTIC,
        "warmth_delta": warmth_delta,
        "assertiveness_delta": assertiveness_delta,
        "confidence": 0.35,
        "summary": "启发式：依据 civility 微调",
        "updated_at": int(time.time()),
    }


def merge_affect_refine_into_profile(profile: dict[str, Any], refine: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return profile
    sample = profile.get("sample")
    if not isinstance(sample, dict):
        sample = {}
        profile = dict(profile)
        profile["sample"] = sample
    if refine is None:
        if "affect_refine" not in sample:
            sample["affect_refine"] = empty_affect_refine()
        return profile

    sample["affect_refine"] = {
        "source": str(refine.get("source") or AFFECT_REFINE_SOURCE_NONE),
        "warmth_delta": round(clamp_affect(float(refine.get("warmth_delta") or 0.0), lower=-0.5, upper=0.5), 3),
        "assertiveness_delta": round(
            clamp_affect(float(refine.get("assertiveness_delta") or 0.0), lower=-0.5, upper=0.5),
            3,
        ),
        "confidence": round(clamp_affect(float(refine.get("confidence") or 0.0), lower=0.0, upper=1.0), 3),
        "summary": str(refine.get("summary") or "")[:256],
        "updated_at": refine.get("updated_at"),
    }
    derived = profile.get("derived")
    if isinstance(derived, dict):
        derived = dict(derived)
        derived["warmth_bias"] = round(
            clamp_affect(
                float(derived.get("warmth_bias") or 0.0) + float(sample["affect_refine"]["warmth_delta"]),
                lower=-0.5,
                upper=0.5,
            ),
            3,
        )
        derived["assertiveness_bias"] = round(
            clamp_affect(
                float(derived.get("assertiveness_bias") or 0.0) + float(sample["affect_refine"]["assertiveness_delta"]),
                lower=-0.5,
                upper=0.5,
            ),
            3,
        )
        profile = dict(profile)
        profile["derived"] = derived
    return profile


def apply_affect_derived(
    persona_warmth: float,
    persona_assertiveness: float,
    derived: dict[str, Any],
) -> tuple[float, float]:
    warmth = persona_warmth
    assertiveness = persona_assertiveness
    warmth_bias = derived.get("warmth_bias")
    if isinstance(warmth_bias, int | float):
        warmth = clamp_affect(warmth + float(warmth_bias))
    assertiveness_bias = derived.get("assertiveness_bias")
    if isinstance(assertiveness_bias, int | float):
        assertiveness = clamp_affect(assertiveness + float(assertiveness_bias))
    return warmth, assertiveness
