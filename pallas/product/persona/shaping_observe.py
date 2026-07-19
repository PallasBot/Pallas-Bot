from __future__ import annotations

import re
from typing import Any

_PERSONA_SECTION_MARKERS = (
    "【本轮牛格塑形】",
    "【情境触发】",
    "【表达习惯参考】",
    "【本轮表达去重】",
    "【语料收尾参考】",
    "【收尾变化参考】",
)

_COMPARE_NOTE = (
    "@ 闲聊与 repeater LLM 均可注入【本轮牛格塑形】/【接话塑形】与动态表达参考；"
    "语料纯规则路径仍主要走 scorer 与 variation 去重。"
)


def extract_persona_sections_from_system_prompt(system_prompt: str) -> dict[str, str]:
    plain = str(system_prompt or "")
    if not plain.strip():
        return {}

    marker_pattern = "|".join(re.escape(item) for item in _PERSONA_SECTION_MARKERS)
    matches = list(re.finditer(marker_pattern, plain))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = str(match.group(0) or "").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plain)
        body = plain[start:end].strip()
        if label and body:
            sections[label] = body
    return sections


def persona_shaping_lines_from_affect_block(affect_block: str) -> list[str]:
    lines: list[str] = []
    for raw in str(affect_block or "").splitlines():
        text = raw.strip()
        if not text or text == "【本轮牛格塑形】":
            continue
        if text.startswith("- "):
            lines.append(text[2:].strip())
        elif text.startswith("-"):
            lines.append(text[1:].strip())
        else:
            lines.append(text)
    return lines[:8]


def build_persona_shaping_summary(
    metadata: dict[str, Any] | None,
    *,
    system_prompt: str = "",
    task: str = "",
) -> dict[str, Any]:
    meta = metadata if isinstance(metadata, dict) else {}
    source_task = str(task or meta.get("task") or "").strip().lower()
    sections = extract_persona_sections_from_system_prompt(system_prompt)

    affect_block = str(meta.get("persona_affect_block") or sections.get("【本轮牛格塑形】") or "").strip()
    dynamic_expression = str(
        meta.get("dynamic_expression_hint") or sections.get("【情境触发】") or sections.get("【表达习惯参考】") or ""
    ).strip()
    if not dynamic_expression:
        trigger = sections.get("【情境触发】", "").strip()
        expression = sections.get("【表达习惯参考】", "").strip()
        parts = [item for item in (trigger, expression) if item]
        dynamic_expression = "\n".join(parts)

    variation_hint = str(meta.get("variation_hint") or sections.get("【本轮表达去重】") or "").strip()
    persona_shaping_active = bool(meta.get("persona_shaping_active")) or bool(affect_block)

    lines = persona_shaping_lines_from_affect_block(affect_block)
    if not lines and affect_block:
        lines = [affect_block[:160]]

    summary: dict[str, Any] = {
        "source_task": source_task or "llm_chat",
        "persona_shaping_active": persona_shaping_active,
        "affect_block": affect_block,
        "dynamic_expression": dynamic_expression,
        "variation_hint": variation_hint,
        "lines": lines,
        "compare_note": _COMPARE_NOTE,
    }
    corpus_ending = sections.get("【语料收尾参考】", "").strip()
    if corpus_ending:
        summary["corpus_ending"] = corpus_ending
    return summary
