"""LLM 可见回复规范化：结构化字段抽取、PASS、字符形态守卫。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class StructuredReply:
    reply: str
    intent: str = ""
    reasoning: str = ""
    mem: str = ""
    from_json: bool = False


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


def parse_structured_reply(raw: str) -> StructuredReply:
    """解析模型原始输出。JSON 缺 reply / 半截对象 → 空 reply（fail-closed）。"""
    if not raw or not str(raw).strip():
        return StructuredReply(reply="")
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
        reply = str(data.get("reply") or "").strip()
        if _is_pass_reply(reply):
            reply = ""
        intent = str(data.get("intent") or "").strip().lower()
        reasoning = str(data.get("reasoning") or "").strip()
        mem_raw = data.get("mem")
        mem = str(mem_raw).strip() if mem_raw is not None else ""
        if mem.lower() in _EMPTY_MEM_TOKENS:
            mem = ""
        return StructuredReply(
            reply=reply,
            intent=intent,
            reasoning=reasoning,
            mem=mem,
            from_json=True,
        )
    if "{" in s:
        return StructuredReply(reply="")
    plain = str(raw).strip()
    if _is_pass_reply(plain):
        return StructuredReply(reply="")
    if _REASONING_PREFIX_RE.match(plain):
        return StructuredReply(reply="")
    if _looks_like_plain_chat(plain):
        return StructuredReply(reply=plain)
    if plain and not any(ch in _BAD_TOKEN_CHARS for ch in plain) and len(plain) <= 200:
        return StructuredReply(reply=plain)
    return StructuredReply(reply="")


def normalize_model_reply(raw: str) -> str:
    """返回可进入后续过滤的可见回复；空串表示不发。"""
    return parse_structured_reply(raw).reply


def validate_reply_chars(text: str) -> tuple[bool, str]:
    """字符形态守卫：不像正常群聊对白则拒绝。"""
    plain = str(text or "").strip()
    if not plain:
        return False, "empty"
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
