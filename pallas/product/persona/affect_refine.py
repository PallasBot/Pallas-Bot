"""可选 LLM 情感 refinement：随 LLM 总闸默认开启，不参与接话热路径。"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

from .affect_baseline import (
    AFFECT_REFINE_SOURCE_HEURISTIC,
    AFFECT_REFINE_SOURCE_LLM,
    empty_affect_refine,
    heuristic_affect_refine_record,
    merge_affect_refine_into_profile,
)
from .affect_refine_client import build_affect_refine_payload, post_affect_refine
from .affect_triggers import apply_affect_refine_triggers_to_profile
from .group_profiler import MIN_MESSAGE_COUNT

_config_lock = Lock()
_cached_enabled: bool | None = None
_cached_min_confidence: float | None = None
_cached_min_interval_sec: int | None = None
_cached_llm_batch_limit: int | None = None

_DEFAULT_MIN_INTERVAL_SEC = 2 * 3600
_DEFAULT_LLM_BATCH_LIMIT = 4


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
            from pallas.product.llm.config import resolve_llm_chat_enabled

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


def affect_refine_min_interval_sec() -> int:
    global _cached_min_interval_sec
    with _config_lock:
        if _cached_min_interval_sec is not None:
            return _cached_min_interval_sec
        raw = repo_env_raw_value("LLM_AFFECT_REFINE_MIN_INTERVAL_SEC")
        if raw is None:
            _cached_min_interval_sec = _DEFAULT_MIN_INTERVAL_SEC
        else:
            try:
                _cached_min_interval_sec = max(300, int(float(raw.strip())))
            except ValueError:
                _cached_min_interval_sec = _DEFAULT_MIN_INTERVAL_SEC
        return _cached_min_interval_sec


def affect_refine_llm_batch_limit() -> int:
    global _cached_llm_batch_limit
    with _config_lock:
        if _cached_llm_batch_limit is not None:
            return _cached_llm_batch_limit
        raw = repo_env_raw_value("LLM_AFFECT_REFINE_BATCH_LIMIT")
        if raw is None:
            _cached_llm_batch_limit = _DEFAULT_LLM_BATCH_LIMIT
        else:
            try:
                _cached_llm_batch_limit = max(0, int(float(raw.strip())))
            except ValueError:
                _cached_llm_batch_limit = _DEFAULT_LLM_BATCH_LIMIT
        return _cached_llm_batch_limit


def clear_affect_refine_config_cache() -> None:
    global _cached_enabled, _cached_min_confidence, _cached_min_interval_sec, _cached_llm_batch_limit
    with _config_lock:
        _cached_enabled = None
        _cached_min_confidence = None
        _cached_min_interval_sec = None
        _cached_llm_batch_limit = None


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


def should_request_llm_affect_refine(
    profile: dict[str, Any],
    prev_profile: dict[str, Any] | None,
    *,
    force_llm: bool = False,
) -> bool:
    if force_llm:
        return True
    if not isinstance(profile.get("derived"), dict):
        return False
    sample = profile.get("sample") if isinstance(profile.get("sample"), dict) else {}
    if int(sample.get("message_count") or 0) < MIN_MESSAGE_COUNT:
        return False
    if not isinstance(prev_profile, dict):
        return True
    prev_sample = prev_profile.get("sample") if isinstance(prev_profile.get("sample"), dict) else {}
    prev_refine = prev_sample.get("affect_refine") if isinstance(prev_sample.get("affect_refine"), dict) else {}
    if prev_refine.get("source") != AFFECT_REFINE_SOURCE_LLM:
        return True
    updated_at = prev_refine.get("updated_at")
    if not isinstance(updated_at, int):
        return True
    return time.time() - updated_at >= affect_refine_min_interval_sec()


def carry_forward_or_heuristic_refine(
    profile: dict[str, Any],
    prev_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(prev_profile, dict):
        prev_sample = prev_profile.get("sample") if isinstance(prev_profile.get("sample"), dict) else {}
        prev_refine = prev_sample.get("affect_refine")
        if isinstance(prev_refine, dict) and prev_refine.get("source") in (
            AFFECT_REFINE_SOURCE_LLM,
            AFFECT_REFINE_SOURCE_HEURISTIC,
        ):
            return merge_affect_refine_into_profile(profile, dict(prev_refine))
    return merge_affect_refine_into_profile(profile, heuristic_affect_refine_record(profile))


async def refine_group_style_affect(
    profile: dict[str, Any],
    *,
    group_id: int,
    message_samples: list[str] | None = None,
    allow_llm: bool = True,
    prev_profile: dict[str, Any] | None = None,
    force_llm: bool = False,
) -> tuple[dict[str, Any], bool]:
    """批次 refresh 时可选调用 AI 仓；返回 (profile, used_llm)。"""
    if not llm_affect_refine_enabled():
        profile = merge_affect_refine_into_profile(profile, empty_affect_refine())
        return apply_affect_refine_triggers_to_profile(profile, None), False

    if not allow_llm or not should_request_llm_affect_refine(profile, prev_profile, force_llm=force_llm):
        profile = carry_forward_or_heuristic_refine(profile, prev_profile)
        return apply_affect_refine_triggers_to_profile(profile, None), False

    payload = build_affect_refine_payload(profile, group_id=group_id, message_samples=message_samples)
    body = await post_affect_refine(payload)
    if not body:
        profile = carry_forward_or_heuristic_refine(profile, prev_profile)
        return apply_affect_refine_triggers_to_profile(profile, None), False

    refine = affect_refine_from_ai_response(body)
    logger.debug(
        "affect refine merged group={} confidence={} warmth_delta={} assertiveness_delta={}",
        group_id,
        refine.get("confidence"),
        refine.get("warmth_delta"),
        refine.get("assertiveness_delta"),
    )
    profile = merge_affect_refine_into_profile(profile, refine)
    return apply_affect_refine_triggers_to_profile(profile, refine), True
