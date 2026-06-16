"""可选 LLM 情感 refinement：随 LLM 总闸默认开启，不参与接话热路径。"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

from nonebot import logger

from src.foundation.config.repo_settings import repo_env_raw_value

from .affect_baseline import (
    AFFECT_REFINE_SOURCE_LLM,
    empty_affect_refine,
    merge_affect_refine_into_profile,
)
from .affect_refine_client import build_affect_refine_payload, post_affect_refine
from .affect_triggers import apply_affect_refine_triggers_to_profile

_config_lock = Lock()
_cached_enabled: bool | None = None
_cached_min_confidence: float | None = None


def llm_affect_refine_enabled() -> bool:
    global _cached_enabled
    with _config_lock:
        if _cached_enabled is not None:
            return _cached_enabled
        raw = repo_env_raw_value("LLM_AFFECT_REFINE_ENABLED")
        if raw is not None:
            sub_enabled = raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            sub_enabled = True
        if not sub_enabled:
            _cached_enabled = False
        else:
            from src.features.llm.config import resolve_llm_chat_enabled

            _cached_enabled = resolve_llm_chat_enabled()
        return _cached_enabled


def affect_refine_min_confidence() -> float:
    global _cached_min_confidence
    with _config_lock:
        if _cached_min_confidence is not None:
            return _cached_min_confidence
        raw = repo_env_raw_value("LLM_AFFECT_REFINE_MIN_CONFIDENCE")
        if raw is None:
            _cached_min_confidence = 0.4
        else:
            try:
                _cached_min_confidence = max(0.0, min(1.0, float(raw.strip())))
            except ValueError:
                _cached_min_confidence = 0.4
        return _cached_min_confidence


def clear_affect_refine_config_cache() -> None:
    global _cached_enabled, _cached_min_confidence
    with _config_lock:
        _cached_enabled = None
        _cached_min_confidence = None


def affect_refine_from_ai_response(body: dict[str, Any]) -> dict[str, Any]:
    confidence = float(body.get("confidence") or 0.0)
    min_confidence = affect_refine_min_confidence()
    warmth_delta = float(body.get("warmth_delta") or 0.0)
    assertiveness_delta = float(body.get("assertiveness_delta") or 0.0)
    if confidence < min_confidence:
        warmth_delta = 0.0
        assertiveness_delta = 0.0
    summary = str(body.get("summary") or "").strip()
    refine: dict[str, Any] = {
        "source": AFFECT_REFINE_SOURCE_LLM,
        "warmth_delta": warmth_delta,
        "assertiveness_delta": assertiveness_delta,
        "confidence": round(confidence, 3),
        "summary": summary[:256],
        "updated_at": int(time.time()),
    }
    triggers = body.get("triggers")
    if isinstance(triggers, list) and triggers:
        refine["triggers"] = triggers
    return refine


async def refine_group_style_affect(
    profile: dict[str, Any],
    *,
    group_id: int,
    message_samples: list[str] | None = None,
) -> dict[str, Any]:
    """批次 refresh 时可选调用 AI 仓；未启用或失败时保留 affect_refine 占位。"""
    if not llm_affect_refine_enabled():
        profile = merge_affect_refine_into_profile(profile, empty_affect_refine())
        return apply_affect_refine_triggers_to_profile(profile, None)

    payload = build_affect_refine_payload(profile, group_id=group_id, message_samples=message_samples)
    body = await post_affect_refine(payload)
    if not body:
        profile = merge_affect_refine_into_profile(profile, empty_affect_refine())
        return apply_affect_refine_triggers_to_profile(profile, None)

    refine = affect_refine_from_ai_response(body)
    logger.debug(
        "affect refine merged group={} confidence={} warmth_delta={} assertiveness_delta={}",
        group_id,
        refine.get("confidence"),
        refine.get("warmth_delta"),
        refine.get("assertiveness_delta"),
    )
    profile = merge_affect_refine_into_profile(profile, refine)
    return apply_affect_refine_triggers_to_profile(profile, refine)
