"""LLM 输出后过滤"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from nonebot import logger

from pallas.core.foundation.logging import log_rate_limited
from pallas.core.platform.ai_callback.task_types import (
    CHAT_DRUNK_TASK_TYPE,
    LEGACY_LLM_CHAT_TASK_TYPES,
)
from pallas.product.llm import corpus_contamination as _corpus_contamination
from pallas.product.llm.models import StructuredChatReply
from pallas.product.llm.tools.select import is_recognition_question

CHAT_HARD_BLOCK_PHRASES = _corpus_contamination.CHAT_HARD_BLOCK_PHRASES
CHAT_SOFT_RETRY_PHRASES = _corpus_contamination.CHAT_SOFT_RETRY_PHRASES
FILLER_ONLY_REPLIES = _corpus_contamination.FILLER_ONLY_REPLIES

OutputFilterProfile = Literal["chat"]
OutputFilterTier = Literal["hard_block", "soft_retry"]

_FILTERED_TASK_TYPES = LEGACY_LLM_CHAT_TASK_TYPES | frozenset({CHAT_DRUNK_TASK_TYPE})

# 续写残片：模型把上一句语气词当成开头（线上大量「吧。…」）
_ORPHAN_LEADING_PARTICLE_RE = re.compile(
    r"^([吧呢啊嗯哦嘛呀哈呵欸唉呃额]+)([。．\.，,、！!？?\s～~]*)+",
)

# 舞台指示括号（叹气/翻白眼/引用等）；保留「（维尼修斯）」类人名注解
_STAGE_DIRECTION_KEYWORDS = (
    "叹气|轻叹|长叹|叹息|呼出一口气|"
    "轻笑|轻笑一声|大笑|苦笑|冷笑|偷笑|微笑|干笑|傻笑|笑出声|噗嗤|笑了|笑|"
    "愣住|愣了一下|愣|懵|呆住|"
    "沉默片刻|沉默|顿了一下|停顿|"
    "装傻|思考|想了想|沉思|思索|琢磨|"
    "点头|摇头|耸肩|摊手|摊了摊手|"
    "白眼|翻白眼|翻了个白眼|"
    "抬头|低头|歪头|侧头|扭头|转头|回头|"
    "挑眉|皱眉|撇嘴|撅嘴|眨眨眼|眨眼|"
    "捂脸|捂嘴|扶额|挠头|揉揉太阳穴|"
    "举手|挥手|摆手|"
    "小声|轻声|低声|嘟囔|嘀咕|咕哝|自言自语|"
    "无奈|尴尬|脸红|不好意思|害羞|"
    "引用|备注|补一句|补充|纠正|"
    "清了清嗓子|咳"
)
_STAGE_DIRECTION_PAREN_RE = re.compile(
    r"[（(]"
    r"[^）)]{0,12}"
    rf"(?:{_STAGE_DIRECTION_KEYWORDS})"
    r"[^）)]{0,10}"
    r"[）)]"
)
# 兜底：行首整段旁白/插科打诨（含未列入关键词的「这谁点的歌啊」等）
_STAGE_DIRECTION_LEADING_RE = re.compile(r"^[（(][^（）()]{1,24}[）)]")

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
    # 内置硬拦词与 WebUI 覆盖合并，避免落盘旧列表吃掉代码新增项
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
    """去掉（叹气）（翻个白眼）等舞台指示括号，保留普通人名注解。"""
    plain = str(text or "").strip()
    if not plain:
        return ""
    cleaned = _STAGE_DIRECTION_PAREN_RE.sub("", plain)
    for _ in range(3):
        next_cleaned = _STAGE_DIRECTION_LEADING_RE.sub("", cleaned, count=1).strip()
        if next_cleaned == cleaned:
            break
        cleaned = next_cleaned
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
    return cleaned.strip(" \t\r\n，,")


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


def _clean_and_guard_reply(text: str, *, task_type: str) -> str:
    from pallas.product.llm.structured_reply import validate_reply_chars

    normalized = str(text or "").strip()
    if not normalized:
        return ""
    cleaned = strip_orphan_leading_particles(normalized)
    if cleaned != normalized:
        log_rate_limited(
            logger,
            "info",
            "llm.output_filter.orphan_particle",
            "LLM orphan leading particle stripped for task [{}], length [{}] -> [{}]",
            task_type,
            len(normalized),
            len(cleaned),
        )
    if not cleaned:
        return ""
    staged = strip_stage_direction_parens(cleaned)
    if staged != cleaned:
        log_rate_limited(
            logger,
            "info",
            "llm.output_filter.stage_direction",
            "LLM stage direction stripped for task [{}], length [{}] -> [{}]",
            task_type,
            len(cleaned),
            len(staged),
        )
    cleaned = staged
    if not cleaned:
        return ""
    if looks_like_truncated_reply(cleaned):
        log_rate_limited(
            logger,
            "info",
            "llm.output_filter.truncated",
            "LLM truncated reply rejected for task [{}]",
            task_type,
        )
        return ""
    ok, reason = validate_reply_chars(cleaned)
    if not ok:
        log_rate_limited(
            logger,
            "info",
            f"llm.output_filter.char_guard.{reason}",
            "LLM reply char guard rejected reply for task [{}], reason [{}]",
            task_type,
            reason,
        )
        return ""
    return cleaned


def _normalize_and_guard_reply(text: str, *, task_type: str) -> str:
    from pallas.product.llm.structured_reply import normalize_model_reply

    normalized = normalize_model_reply(text)
    if not normalized:
        if str(text or "").strip():
            logger.info("LLM structured reply turned out empty for task [{}]", task_type)
        return ""
    return _clean_and_guard_reply(normalized, task_type=task_type)


def _press_reply_to_limit(text: str, *, max_len: int) -> str:
    """把整段按断点截到 max_len 内：优先句子结尾/行/空格，截不利落则原样返回。"""
    plain = str(text or "").strip()
    if not plain or max_len <= 0 or len(plain) <= max_len:
        return plain
    for index in range(max_len - 1, 0, -1):
        if plain[index] not in "。！？!?；;，,、":
            continue
        tail = plain[: index + 1].strip()
        if tail and not looks_like_truncated_reply(tail):
            return tail
    for index in range(max_len - 1, 0, -1):
        if plain[index] not in " \t":
            continue
        tail = plain[:index].strip()
        if tail and not looks_like_truncated_reply(tail):
            return tail
    return plain


def _split_reply_to_fit(text: str, *, max_len: int, max_segments: int = 3) -> list[str] | None:
    """把超限的单泡文本按句读断点切成「每段 ≤max_len」的多泡，尽量保住完整语义。

    只在能干净拆分（每个切出的段都不超上限、且确有拆分）时返回分段列表；
    单句内部找不到可断点、或段数超出限制（再 fold 会重新超限）则返回 None，
    交由调用方走压短/回落/静默。
    """
    if not text or max_len <= 0 or len(text) <= max_len:
        return None
    plain = str(text or "").strip()
    hard_tokens: list[str] = []
    start = 0
    for index, ch in enumerate(plain):
        if ch not in "。！？!?；;\n":
            continue
        token = plain[start : index + 1].strip()
        if token:
            hard_tokens.append(token)
        start = index + 1
    tail = plain[start:].strip()
    if tail:
        hard_tokens.append(tail)
    units: list[str] = []
    for token in hard_tokens:
        if len(token) <= max_len:
            units.append(token)
            continue
        sub = _soft_split_unit(token, max_len=max_len)
        if sub is None:
            return None
        units.extend(sub)
    if not units:
        return None
    segments: list[str] = []
    buffer = ""
    for unit in units:
        if buffer and len(buffer) + len(unit) > max_len:
            segments.append(buffer)
            buffer = unit
        else:
            buffer += unit
    if buffer:
        segments.append(buffer)
    segments = [seg.strip() for seg in segments if seg.strip()]
    if len(segments) < 2 or len(segments) > max_segments:
        return None
    return segments


def _soft_split_unit(token: str, *, max_len: int) -> list[str] | None:
    """单个句子超限时按中文逗号/空格软切到每段 ≤max_len，切不利落返回 None。"""
    pieces: list[str] = []
    remainder = token.strip()
    while len(remainder) > max_len:
        cut_at = remainder.rfind("，", 0, max_len)
        if cut_at < 0:
            for seps in ("、", " "):
                candidate = remainder.rfind(seps, 0, max_len)
                if candidate > 0:
                    cut_at = candidate
                    break
        if cut_at < 1:
            return None
        pieces.append(remainder[:cut_at].strip())
        remainder = remainder[cut_at + 1 :].strip()
    if remainder:
        pieces.append(remainder)
    return [piece for piece in pieces if piece] or None


def _enforce_max_length(text: str, *, task: dict, task_type: str) -> str:
    """行为/场景长度违约：超上限先断点压短，压不短才回落 fallback 或静默。"""
    try:
        max_len = int(task.get("reply_max_length") or 0)
    except (TypeError, ValueError):
        max_len = 0
    if max_len <= 0 or not text:
        return text
    if len(text) <= max_len:
        return text
    pressed = _press_reply_to_limit(text, max_len=max_len)
    if pressed and pressed != text:
        log_rate_limited(
            logger,
            "info",
            "llm.output_filter.length_press",
            "LLM reply pressed to length cap for task [{}], len [{}] max [{}] -> [{}]",
            task_type,
            len(text),
            max_len,
            pressed,
        )
        return pressed
    fallback = str(task.get("fallback_text") or "").strip()
    if fallback and fallback != text and len(fallback) <= max_len:
        logger.info(
            "LLM reply length over cap for task [{}], len [{}] max [{}] -> fallback",
            task_type,
            len(text),
            max_len,
        )
        return fallback
    logger.info(
        "LLM reply length over cap for task [{}], len [{}] max [{}] -> silent",
        task_type,
        len(text),
        max_len,
    )
    return ""


def resolve_output_filtered_reply(task: dict, reply_text: str) -> str:
    """返回可投递文本；空串表示静默不发。"""
    from pallas.product.llm.structured_reply import parse_structured_reply

    return resolve_output_filtered_chat_reply(task, parse_structured_reply(reply_text)).logical_text


def _resolve_filtered_fallback(task: dict, *, profile: OutputFilterProfile, task_type: str) -> StructuredChatReply:
    fallback = str(task.get("fallback_text") or "").strip()
    guarded_fallback = _clean_and_guard_reply(fallback, task_type=task_type)
    if guarded_fallback and match_output_filter(guarded_fallback, profile) is None:
        return StructuredChatReply.single(guarded_fallback)
    return StructuredChatReply()


def resolve_output_filtered_chat_reply(task: dict, reply: StructuredChatReply) -> StructuredChatReply:
    """过滤已解析的聊天气泡，不重新解释其文本为模型 JSON。"""
    task_type = str(task.get("task_type") or "").strip()
    profile = profile_for_task_type(task_type)
    if profile is None:
        return reply
    filter_enabled = output_filter_enabled()
    reply_segments: list[str] = []
    for segment in reply.reply_segments:
        cleaned = _clean_and_guard_reply(segment, task_type=task_type)
        if not cleaned:
            continue
        hit = match_output_filter(cleaned, profile) if filter_enabled else None
        if hit is not None:
            logger.info(
                "LLM output filter [{}] dropped segment for task [{}], phrase [{}]",
                hit.tier,
                task_type,
                hit.phrase,
            )
            continue
        reply_segments.append(cleaned)
    if not reply_segments:
        if filter_enabled:
            return _resolve_filtered_fallback(task, profile=profile, task_type=task_type)
        return StructuredChatReply()
    filtered = replace(reply, reply_segments=tuple(reply_segments))
    text = filtered.logical_text
    try:
        max_len = int(task.get("reply_max_length") or 0)
    except (TypeError, ValueError):
        max_len = 0
    # 多泡回复：每个气泡各自都落在单点上限内，就保持分条投递，而不是把
    # 整串 join 后按一刀切压短/静默（否则合理的分段长回复会被整个吞掉）。
    if max_len > 0 and filtered.reply_segments and all(len(seg) <= max_len for seg in filtered.reply_segments):
        log_rate_limited(
            logger,
            "info",
            "llm.output_filter.multi_bubble_kept",
            "LLM reply kept as segments for task [{}], len [{}] max [{}], segments [{}]",
            task_type,
            len(text),
            max_len,
            len(filtered.reply_segments),
        )
        text = filtered.logical_text
    else:
        enforced_text = text
        split_done = False
        # 超限时：仅当是识别问句（这是谁/这是什么/啥梗）时，优先按句读切成每段
        # 都 ≤max_len 的多泡投递，保住被硬截断的答案；闲聊短句保持精简短泡不拆分。
        # 不限制单泡：识别问句模型常输出长描述或结构化多段（join 后含换行），
        # 均可能整体超限，需按断点重切而非一刀切压短。
        is_recognition = is_recognition_question(str(task.get("user_text") or ""))
        if is_recognition and max_len > 0 and len(text) > max_len:
            split = _split_reply_to_fit(text, max_len=max_len)
            if split:
                log_rate_limited(
                    logger,
                    "info",
                    "llm.output_filter.pressed_split_multi_bubble",
                    "LLM reply over length cap split into segments for task [{}], len [{}] max [{}], segments [{}]",
                    task_type,
                    len(text),
                    max_len,
                    len(split),
                )
                filtered = replace(filtered, reply_segments=tuple(split))
                text = filtered.logical_text
                split_done = True
        if not split_done:
            enforced_text = _enforce_max_length(text, task=task, task_type=task_type)
            if not enforced_text:
                return StructuredChatReply()
            if enforced_text != text:
                filtered = replace(filtered, reply_segments=(enforced_text,))
                text = enforced_text
    if not filter_enabled:
        return filtered
    hit = match_output_filter(text, profile) or match_output_filter("".join(filtered.reply_segments), profile)
    if hit is None:
        return filtered
    fallback_reply = _resolve_filtered_fallback(task, profile=profile, task_type=task_type)
    if fallback_reply.reply_segments:
        logger.info(
            "LLM output filter [{}] fell back for task [{}], phrase [{}]",
            hit.tier,
            task_type,
            hit.phrase,
        )
        return fallback_reply
    logger.info(
        "LLM output filter [{}] silenced reply for task [{}], phrase [{}]",
        hit.tier,
        task_type,
        hit.phrase,
    )
    return StructuredChatReply()
