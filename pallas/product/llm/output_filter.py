"""LLM 输出后过滤"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nonebot import logger

from pallas.core.platform.ai_callback.task_types import (
    CHAT_DRUNK_TASK_TYPE,
    LEGACY_LLM_CHAT_TASK_TYPES,
    REPEATER_LLM_TASK_TYPES,
    REPEATER_POLISH_LITE_TASK_TYPE,
)
from pallas.product.llm import corpus_contamination as _corpus_contamination

CHAT_HARD_BLOCK_PHRASES = _corpus_contamination.CHAT_HARD_BLOCK_PHRASES
CHAT_SOFT_RETRY_PHRASES = _corpus_contamination.CHAT_SOFT_RETRY_PHRASES
POLISH_LITE_HARD_BLOCK_PHRASES = _corpus_contamination.POLISH_LITE_HARD_BLOCK_PHRASES
POLISH_LITE_SOFT_RETRY_PHRASES = _corpus_contamination.POLISH_LITE_SOFT_RETRY_PHRASES
FILLER_ONLY_REPLIES = _corpus_contamination.FILLER_ONLY_REPLIES

OutputFilterProfile = Literal["chat", "polish_lite"]
OutputFilterTier = Literal["hard_block", "soft_retry"]

_FILTERED_TASK_TYPES = LEGACY_LLM_CHAT_TASK_TYPES | REPEATER_LLM_TASK_TYPES | frozenset({CHAT_DRUNK_TASK_TYPE})


@dataclass(frozen=True, slots=True)
class OutputFilterHit:
    tier: OutputFilterTier
    phrase: str
    profile: OutputFilterProfile


def output_filter_enabled() -> bool:
    from pallas.product.llm.config import get_llm_config

    cfg = get_llm_config()
    return bool(cfg.llm_output_filter_enabled)


def profile_for_task_type(task_type: str) -> OutputFilterProfile | None:
    normalized = str(task_type or "").strip()
    if normalized not in _FILTERED_TASK_TYPES:
        return None
    if normalized == REPEATER_POLISH_LITE_TASK_TYPE:
        return "polish_lite"
    return "chat"


def _unique_phrases(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for phrase in group:
            item = str(phrase or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
    return tuple(out)


def phrases_for_profile(profile: OutputFilterProfile, tier: OutputFilterTier) -> tuple[str, ...]:
    from pallas.product.llm.config import get_llm_config

    cfg = get_llm_config()
    chat_hard = tuple(phrase for phrase in cfg.llm_output_filter_chat_hard_phrases if phrase)
    chat_soft = tuple(phrase for phrase in cfg.llm_output_filter_chat_soft_phrases if phrase)
    polish_hard = tuple(phrase for phrase in cfg.llm_output_filter_polish_lite_hard_phrases if phrase)
    polish_soft = tuple(phrase for phrase in cfg.llm_output_filter_polish_lite_soft_phrases if phrase)
    # 内置硬拦词与 WebUI 覆盖合并，避免落盘旧列表吃掉代码新增项
    if profile == "polish_lite":
        if tier == "hard_block":
            return _unique_phrases(
                CHAT_HARD_BLOCK_PHRASES,
                POLISH_LITE_HARD_BLOCK_PHRASES,
                chat_hard,
                polish_hard,
            )
        return _unique_phrases(CHAT_SOFT_RETRY_PHRASES, POLISH_LITE_SOFT_RETRY_PHRASES, chat_soft, polish_soft)
    if tier == "hard_block":
        return _unique_phrases(CHAT_HARD_BLOCK_PHRASES, chat_hard)
    return _unique_phrases(CHAT_SOFT_RETRY_PHRASES, chat_soft)


def is_filler_only_reply(text: str) -> bool:
    plain = str(text or "").strip()
    if not plain:
        return False
    compact = plain.strip("，,。！!？?~～ ")
    return plain in FILLER_ONLY_REPLIES or compact in FILLER_ONLY_REPLIES


def match_output_filter(text: str, profile: OutputFilterProfile) -> OutputFilterHit | None:
    plain = str(text or "").strip()
    if not plain:
        return None
    from pallas.product.llm.corpus_contamination import match_unsafe_learn_text

    unsafe_hit = match_unsafe_learn_text(plain)
    if unsafe_hit:
        return OutputFilterHit(tier="hard_block", phrase=unsafe_hit, profile=profile)
    if is_filler_only_reply(plain):
        return OutputFilterHit(tier="hard_block", phrase="filler_only", profile=profile)
    for phrase in phrases_for_profile(profile, "hard_block"):
        if phrase in plain:
            return OutputFilterHit(tier="hard_block", phrase=phrase, profile=profile)
    for phrase in phrases_for_profile(profile, "soft_retry"):
        if phrase in plain:
            return OutputFilterHit(tier="soft_retry", phrase=phrase, profile=profile)
    return None


def _normalize_and_guard_reply(text: str, *, task_type: str) -> str:
    from pallas.product.llm.structured_reply import normalize_model_reply, validate_reply_chars

    normalized = normalize_model_reply(text)
    if not normalized:
        if str(text or "").strip():
            logger.info("LLM structured reply empty task_type={}", task_type)
        return ""
    ok, reason = validate_reply_chars(normalized)
    if not ok:
        logger.info(
            "LLM reply char guard reject task_type={} reason={}",
            task_type,
            reason,
        )
        return ""
    return normalized


def _enforce_max_length(text: str, *, task: dict, task_type: str) -> str:
    """行为/场景长度违约：超上限过多则回落 fallback 或静默。"""
    try:
        max_len = int(task.get("reply_max_length") or 0)
    except (TypeError, ValueError):
        max_len = 0
    if max_len <= 0 or not text:
        return text
    if len(text) <= max_len:
        return text
    # 轻微超长仍放行；明显违约才回落
    if len(text) <= max_len + 12:
        return text
    fallback = str(task.get("fallback_text") or "").strip()
    if fallback and fallback != text and len(fallback) <= max_len + 12:
        logger.info(
            "LLM reply length over cap task_type={} len={} max={} -> fallback",
            task_type,
            len(text),
            max_len,
        )
        return fallback
    logger.info(
        "LLM reply length over cap task_type={} len={} max={} -> silent",
        task_type,
        len(text),
        max_len,
    )
    return ""


def resolve_output_filtered_reply(task: dict, reply_text: str) -> str:
    """返回可投递文本；空串表示静默不发。"""
    raw = str(reply_text or "").strip()
    task_type = str(task.get("task_type") or "").strip()
    profile = profile_for_task_type(task_type)
    if profile is None:
        return raw
    text = _normalize_and_guard_reply(raw, task_type=task_type) if raw else ""
    if not text:
        return ""
    text = _enforce_max_length(text, task=task, task_type=task_type)
    if not text:
        return ""
    if not output_filter_enabled():
        return text
    hit = match_output_filter(text, profile)
    if hit is None:
        return text
    fallback = str(task.get("fallback_text") or "").strip()
    if fallback and fallback != text:
        guarded_fallback = _normalize_and_guard_reply(fallback, task_type=task_type)
        if guarded_fallback and match_output_filter(guarded_fallback, profile) is None:
            logger.info(
                "LLM output filter {} task_type={} phrase={} -> fallback",
                hit.tier,
                task_type,
                hit.phrase,
            )
            return guarded_fallback
    logger.info(
        "LLM output filter {} task_type={} phrase={} -> silent",
        hit.tier,
        task_type,
        hit.phrase,
    )
    return ""
