from __future__ import annotations

import re
from typing import Any

from .prompt_guard import sanitize_prompt_literal

_CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]", re.IGNORECASE)
_AT_PLAIN_RE = re.compile(r"@[^\s@，,。！!？?：:;；]{1,24}")
# 群聊短接话常见 3～4 字；过严会漏掉「然后呢」「懂了吗」等可用参考
_EXPRESSION_REF_MIN_LEN = 3
_EXPRESSION_REF_MIN_CJK = 2
_EXPRESSION_REF_MAX_LEN = 48


def clean_expression_reference_text(text: str, *, max_len: int = _EXPRESSION_REF_MAX_LEN) -> str:
    out = _CQ_CODE_RE.sub("", str(text or ""))
    out = _AT_PLAIN_RE.sub("", out)
    out = re.sub(r"\s+", " ", out).strip()
    return sanitize_prompt_literal(out, max_len=max_len)


def is_usable_expression_reference(
    text: str,
    *,
    min_len: int = _EXPRESSION_REF_MIN_LEN,
    min_cjk: int = _EXPRESSION_REF_MIN_CJK,
) -> bool:
    cleaned = clean_expression_reference_text(text, max_len=512)
    if not cleaned or "[CQ:" in cleaned.upper():
        return False
    if len(cleaned) < min_len:
        return False
    if cleaned.isdigit() or re.fullmatch(r"[\d\s]+", cleaned):
        return False
    cjk_count = sum(1 for char in cleaned if "\u4e00" <= char <= "\u9fff")
    if cjk_count == 0:
        return False
    if cjk_count < min_cjk and len(cleaned) < 12:
        return False
    digit_ratio = sum(char.isdigit() for char in cleaned) / max(len(cleaned), 1)
    if digit_ratio >= 0.5:
        return False
    return True


def filter_expression_reference_candidates(candidates: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        cleaned = clean_expression_reference_text(item)
        if not cleaned or cleaned in seen:
            continue
        if not is_usable_expression_reference(cleaned):
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def match_message_affect_triggers(plain_text: str, triggers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plain = str(plain_text or "").strip().lower()
    if not plain or not triggers:
        return []
    matched: list[dict[str, Any]] = []
    for item in triggers:
        if not isinstance(item, dict):
            continue
        phrase = str(item.get("phrase") or "").strip().lower()
        if phrase and phrase in plain:
            matched.append(item)
    matched.sort(key=lambda row: float(row.get("weight") or 0.0), reverse=True)
    return matched[:3]


def build_affect_trigger_turn_hint(plain_text: str, matched_triggers: list[dict[str, Any]]) -> str:
    if not matched_triggers:
        return ""

    hints: list[str] = []
    for item in matched_triggers[:2]:
        phrase = sanitize_prompt_literal(str(item.get("phrase") or ""), max_len=24)
        if not phrase:
            continue
        warmth_delta = float(item.get("warmth_delta") or 0.0)
        assertiveness_delta = float(item.get("assertiveness_delta") or 0.0)
        tone_parts: list[str] = []
        if warmth_delta >= 0.08:
            tone_parts.append("语气可稍软、更接梗")
        elif warmth_delta <= -0.08:
            tone_parts.append("语气偏克制")
        if assertiveness_delta >= 0.08:
            tone_parts.append("可适度顶一句")
        elif assertiveness_delta <= -0.08:
            tone_parts.append("少反呛")
        if tone_parts:
            hints.append(f"提到「{phrase}」时，{'，'.join(tone_parts)}")
        else:
            hints.append(f"提到「{phrase}」时，按本群习惯接话")
    if not hints:
        return ""
    return "【情境触发】" + "；".join(hints)


def format_situational_expression_pairs(
    matched_triggers: list[dict[str, Any]],
    candidates: list[str],
    *,
    user_text: str = "",
) -> list[str]:
    lines: list[str] = []
    remaining = filter_expression_reference_candidates([str(item or "").strip() for item in candidates])

    for item in matched_triggers[:3]:
        phrase = sanitize_prompt_literal(str(item.get("phrase") or ""), max_len=24)
        if not phrase:
            continue
        if not remaining:
            break
        reply = remaining.pop(0)
        lines.append(f"当「{phrase}」时，可参考本群说法「{reply}」（勿照抄 @、CQ 码或半句碎片）")

    if remaining and not matched_triggers:
        query_snippet = sanitize_prompt_literal(str(user_text or "").strip()[:16], max_len=16)
        for reply in remaining[:2]:
            if query_snippet:
                lines.append(f"针对「{query_snippet}」，可参考本群说法「{reply}」（勿照抄 @、CQ 码或半句碎片）")
            else:
                lines.append(f"可参考本群说法「{reply}」（勿照抄 @、CQ 码或半句碎片）")
    return lines


def format_dynamic_expression_hint(trigger_hint: str, situational_lines: list[str]) -> str:
    sections: list[str] = []
    if str(trigger_hint or "").strip():
        sections.append(str(trigger_hint).strip())
    if situational_lines:
        sections.append("【表达习惯参考】" + "；".join(situational_lines))
    if not sections:
        return ""
    return "\n" + "\n".join(sections) + "。"
