from __future__ import annotations

from typing import Any

from .prompt_guard import sanitize_prompt_literal


def compile_expression_habits_lines(style_profile: dict[str, Any] | None) -> list[str]:
    if not isinstance(style_profile, dict):
        return []

    sample = style_profile.get("sample") if isinstance(style_profile.get("sample"), dict) else {}
    derived = style_profile.get("derived") if isinstance(style_profile.get("derived"), dict) else {}

    triggers = sample.get("affect_triggers") if isinstance(sample.get("affect_triggers"), list) else []
    phrases: list[str] = []
    seen: set[str] = set()
    for item in triggers[:6]:
        if not isinstance(item, dict):
            continue
        phrase = sanitize_prompt_literal(
            str(item.get("phrase") or item.get("trigger") or item.get("text") or "").strip(),
            max_len=24,
        )
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        phrases.append(phrase)

    lines: list[str] = []
    if phrases:
        lines.append("群里常接这些说法/梗：" + "、".join(phrases[:3]))

    length_pref = str(derived.get("length_pref") or "").strip()
    chaos_bias = float(derived.get("chaos_bias") or 0.0)
    if length_pref == "short" and chaos_bias >= 0.15:
        lines.append("顺手短句更自然，别解释太满")

    return lines


def build_expression_habits_suffix(style_profile: dict[str, Any] | None) -> str:
    lines = compile_expression_habits_lines(style_profile)
    if not lines:
        return ""
    return "\n【表达习惯参考】" + "；".join(lines) + "。"
