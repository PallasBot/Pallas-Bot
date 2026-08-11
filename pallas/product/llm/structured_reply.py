"""LLM 可见回复规范化：结构化字段抽取、PASS、字符形态守卫。"""

from __future__ import annotations

import json
import re

from pallas.product.llm.models import StructuredChatReply

_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\s*```$")
_PASS_RE = re.compile(r"^PASS\b", re.IGNORECASE)
_REASONING_PREFIX_RE = re.compile(
    r"^[\s\-•]*("
    r"input|speaker|intent|decision|style|analysis|judgment|"
    r"thinking|scenario|reply strategy|context|background|mode"
    r"|输入|发言人|意图|决策|风格|分析|判断|思考|场景|回复策略|上下文|背景|模式"
    r")[:：]",
    re.IGNORECASE,
)
_BAD_TOKEN_CHARS = frozenset("<>{}|｜▁")
_ALLOWED_ASCII_PUNCT = frozenset(".,?!;:'\"()-_~`@#&+*=%^/\n\t \r")
_EMPTY_MEM_TOKENS = frozenset({"无", "none", "n/a", "null", "无内容", "无可记"})
_STANDALONE_CHAT_RE = re.compile(r"^[？?]$")


StructuredReply = StructuredChatReply


def _normalize_sticker_intent(value: object) -> str:
    if str(value or "").strip().lower() == "send":
        return "send"
    if not isinstance(value, dict):
        return "none"
    from pallas.product.llm.sticker_labels import ACTION_VOCABULARY, EMOTION_VOCABULARY, TONE_VOCABULARY

    tokens: list[str] = []
    for key, vocabulary in (("emotion", EMOTION_VOCABULARY), ("action", ACTION_VOCABULARY), ("tone", TONE_VOCABULARY)):
        raw = value.get(key)
        supplied = {str(item).strip() for item in raw} if isinstance(raw, list) else {str(raw or "").strip()}
        tokens.extend(f"{key}:{item}" for item in vocabulary if item in supplied)
    usage = value.get("usage")
    values = usage if isinstance(usage, list) else [usage]
    tokens.extend(f"usage:{str(item).strip()[:160]}" for item in values if str(item or "").strip())
    return " ".join(tokens) or "none"


def _strip_fences(text: str) -> str:
    s = text.strip()
    s = _FENCE_OPEN_RE.sub("", s, count=1)
    s = _FENCE_CLOSE_RE.sub("", s, count=1)
    return s.strip()


def _is_pass_reply(text: str) -> bool:
    return bool(_PASS_RE.match(str(text or "").strip()))


def _looks_like_plain_chat(text: str) -> bool:
    cleaned = text.strip()
    if not (3 <= len(cleaned) <= 200):
        return False
    if not any(ch.isalpha() or "\u4e00" <= ch <= "\u9fff" for ch in cleaned):
        return False
    if any(ch in _BAD_TOKEN_CHARS for ch in cleaned):
        return False
    if _REASONING_PREFIX_RE.match(cleaned):
        return False
    return True


def _segments_from_json(data: dict[object, object]) -> tuple[str, ...]:
    legacy_reply = data.get("reply")
    if legacy_reply is not None:
        if not isinstance(legacy_reply, str):
            return ()
        reply = legacy_reply.strip()
        return () if _is_pass_reply(reply) else (reply,) if reply else ()
    raw_segments = data.get("reply_segments")
    if not isinstance(raw_segments, list):
        return ()
    if not raw_segments or any(not isinstance(item, str) for item in raw_segments):
        return ()
    segments = tuple(item.strip() for item in raw_segments)
    if any(not item or _is_pass_reply(item) or not validate_reply_chars(item)[0] for item in segments):
        return ()
    if len(segments) <= 3:
        return segments
    return (*segments[:2], "\n".join(segments[2:]))


def parse_structured_reply(raw: str) -> StructuredChatReply:
    """解析模型原始输出。JSON 缺 reply / 半截对象 → 空 reply（fail-closed）。"""
    if not raw or not str(raw).strip():
        return StructuredChatReply()
    s = _strip_fences(str(raw))
    data = None
    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        start = s.find("{")
        if start >= 0:
            try:
                data, _end = json.JSONDecoder().raw_decode(s[start:])
            except json.JSONDecodeError:
                data = None
    if isinstance(data, dict):
        reply_segments = _segments_from_json(data)
        intent = str(data.get("intent") or "").strip().lower()
        reasoning = str(data.get("reasoning") or "").strip()
        mem_raw = data.get("mem")
        mem = str(mem_raw).strip() if mem_raw is not None else ""
        if mem.lower() in _EMPTY_MEM_TOKENS:
            mem = ""
        sticker_intent = _normalize_sticker_intent(data.get("sticker"))
        return StructuredChatReply(
            reply_segments=reply_segments,
            intent=intent,
            reasoning=reasoning,
            mem=mem,
            sticker_intent=sticker_intent,
            from_json=True,
        )
    if "{" in s:
        return StructuredChatReply()
    plain = str(raw).strip()
    if _is_pass_reply(plain):
        return StructuredChatReply()
    if _REASONING_PREFIX_RE.match(plain):
        return StructuredChatReply()
    if _looks_like_plain_chat(plain):
        return StructuredChatReply.single(plain)
    if plain and not any(ch in _BAD_TOKEN_CHARS for ch in plain) and len(plain) <= 200:
        return StructuredChatReply.single(plain)
    return StructuredChatReply()


def normalize_model_reply(raw: str) -> str:
    """返回可进入后续过滤的可见回复；空串表示不发。"""
    return parse_structured_reply(raw).logical_text


def validate_reply_chars(text: str) -> tuple[bool, str]:
    """字符形态守卫：不像正常群聊对白则拒绝。"""
    plain = str(text or "").strip()
    if not plain:
        return False, "empty"
    if _STANDALONE_CHAT_RE.fullmatch(plain):
        return True, ""
    if len(plain) > 500:
        return False, f"too long ({len(plain)})"
    cjk_count = 0
    letter_count = 0
    for ch in plain:
        code = ord(ch)
        if ch in _BAD_TOKEN_CHARS:
            return False, f"bad token char {ch!r}"
        if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            cjk_count += 1
            continue
        if 0x3000 <= code <= 0x303F:
            continue
        if 0xFF00 <= code <= 0xFFEF:
            continue
        if ch in _ALLOWED_ASCII_PUNCT:
            continue
        if code < 0x80 and ch.isalnum():
            if ch.isalpha():
                letter_count += 1
            continue
        return False, f"unexpected char {ch!r}"
    if cjk_count == 0 and letter_count == 0:
        return False, "no letter content"
    return True, ""
