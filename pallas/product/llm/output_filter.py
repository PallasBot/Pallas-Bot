"""LLM 输出后过滤"""

from __future__ import annotations

import re
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

# 续写残片：模型把上一句语气词当成开头（线上大量「吧。…」）
_ORPHAN_LEADING_PARTICLE_RE = re.compile(
    r"^([吧呢啊嗯哦嘛呀哈呵欸唉呃额]+)([。．\.，,、！!？?\s～~]*)+",
)

# 舞台指示括号（叹气/笑/装傻等）；保留「（维尼修斯）」类人名注解
_STAGE_DIRECTION_PAREN_RE = re.compile(
    r"[（(]"
    r"[^）)]{0,10}"
    r"(?:叹气|轻笑|大笑|苦笑|冷笑|偷笑|微笑|干笑|傻笑|笑|"
    r"愣住|愣了一下|愣|"
    r"沉默片刻|沉默|"
    r"装傻|思考|沉思|点头|摇头|耸肩|"
    r"小声|轻声|低声|嘟囔|无奈|尴尬|脸红)"
    r"[^）)]{0,8}"
    r"[）)]"
)

_TRUNCATED_TAIL_RE = re.compile(r"(?:把别的|打成|以及|还有|然后|接着|或者|但是|不过|因为|所以|如果|要是)$")
_TRUNCATED_CONNECTOR_RE = re.compile(r"(?:把|被|跟|和|与|给|让|用|从|向|往)[\u4e00-\u9fff]{0,2}$")


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


def strip_orphan_leading_particles(text: str) -> str:
    """去掉开头的续写语气残片；只剩标点时返回空串。"""
    plain = str(text or "").strip()
    if not plain:
        return ""
    cleaned = plain
    for _ in range(3):
        next_text = _ORPHAN_LEADING_PARTICLE_RE.sub("", cleaned, count=1).strip()
        if next_text == cleaned:
            break
        cleaned = next_text
    if not cleaned:
        return ""
    # 只剩标点/语气
    if not cleaned.strip("，,。！!？?~～ …."):
        return ""
    return cleaned


def strip_stage_direction_parens(text: str) -> str:
    """去掉（叹气）（笑）等舞台指示括号，保留普通人名注解。"""
    plain = str(text or "").strip()
    if not plain:
        return ""
    cleaned = _STAGE_DIRECTION_PAREN_RE.sub("", plain)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
    return cleaned.strip(" ，,")


def looks_like_truncated_reply(text: str) -> bool:
    """短句停在半截连词/「把别的」等，像被截断。"""
    plain = str(text or "").strip()
    if not plain or len(plain) < 6 or len(plain) > 48:
        return False
    if _TRUNCATED_TAIL_RE.search(plain):
        return True
    if _TRUNCATED_CONNECTOR_RE.search(plain) and not plain.endswith(("吧", "呢", "啊", "呀", "嘛", "咯")):
        return True
    return False


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
    cleaned = strip_orphan_leading_particles(normalized)
    if cleaned != normalized:
        logger.info(
            "LLM orphan leading particle stripped task_type={} before={!r} after={!r}",
            task_type,
            normalized[:48],
            cleaned[:48],
        )
    if not cleaned:
        return ""
    staged = strip_stage_direction_parens(cleaned)
    if staged != cleaned:
        logger.info(
            "LLM stage direction stripped task_type={} before={!r} after={!r}",
            task_type,
            cleaned[:48],
            staged[:48],
        )
    cleaned = staged
    if not cleaned:
        return ""
    if looks_like_truncated_reply(cleaned):
        logger.info("LLM truncated reply rejected task_type={} text={!r}", task_type, cleaned[:48])
        return ""
    ok, reason = validate_reply_chars(cleaned)
    if not ok:
        logger.info(
            "LLM reply char guard reject task_type={} reason={}",
            task_type,
            reason,
        )
        return ""
    return cleaned


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
