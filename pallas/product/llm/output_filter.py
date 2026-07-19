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


def phrases_for_profile(profile: OutputFilterProfile, tier: OutputFilterTier) -> tuple[str, ...]:
    from pallas.product.llm.config import get_llm_config

    cfg = get_llm_config()
    chat_hard = tuple(phrase for phrase in cfg.llm_output_filter_chat_hard_phrases if phrase)
    chat_soft = tuple(phrase for phrase in cfg.llm_output_filter_chat_soft_phrases if phrase)
    polish_hard = tuple(phrase for phrase in cfg.llm_output_filter_polish_lite_hard_phrases if phrase)
    polish_soft = tuple(phrase for phrase in cfg.llm_output_filter_polish_lite_soft_phrases if phrase)
    if profile == "polish_lite":
        if tier == "hard_block":
            return chat_hard + polish_hard
        return chat_soft + polish_soft
    if tier == "hard_block":
        return chat_hard
    return chat_soft


def match_output_filter(text: str, profile: OutputFilterProfile) -> OutputFilterHit | None:
    plain = str(text or "").strip()
    if not plain:
        return None
    from pallas.product.llm.corpus_contamination import match_unsafe_learn_text

    unsafe_hit = match_unsafe_learn_text(plain)
    if unsafe_hit:
        return OutputFilterHit(tier="hard_block", phrase=unsafe_hit, profile=profile)
    for phrase in phrases_for_profile(profile, "hard_block"):
        if phrase in plain:
            return OutputFilterHit(tier="hard_block", phrase=phrase, profile=profile)
    for phrase in phrases_for_profile(profile, "soft_retry"):
        if phrase in plain:
            return OutputFilterHit(tier="soft_retry", phrase=phrase, profile=profile)
    return None


def resolve_output_filtered_reply(task: dict, reply_text: str) -> str:
    """返回可投递文本；空串表示静默不发。"""
    text = str(reply_text or "").strip()
    if not text or not output_filter_enabled():
        return text
    task_type = str(task.get("task_type") or "").strip()
    profile = profile_for_task_type(task_type)
    if profile is None:
        return text
    hit = match_output_filter(text, profile)
    if hit is None:
        return text
    fallback = str(task.get("fallback_text") or "").strip()
    if fallback and fallback != text and match_output_filter(fallback, profile) is None:
        logger.info(
            "LLM output filter {} task_type={} phrase={} -> fallback",
            hit.tier,
            task_type,
            hit.phrase,
        )
        return fallback
    logger.info(
        "LLM output filter {} task_type={} phrase={} -> silent",
        hit.tier,
        task_type,
        hit.phrase,
    )
    return ""
