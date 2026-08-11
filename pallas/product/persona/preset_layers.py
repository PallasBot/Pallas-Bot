"""预设分层：knowledges / relationships 编译进 persona prompt。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .prompt_guard import sanitize_prompt_literal


class PresetLayers(BaseModel):
    knowledges: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)


def normalize_layer_lines(raw: Any, *, limit: int = 12, max_len: int = 120) -> list[str]:
    if not isinstance(raw, list):
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = sanitize_prompt_literal(str(item or "").strip(), max_len=max_len)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(text)
        if len(lines) >= limit:
            break
    return lines


def extract_preset_layers(
    bot_persona: dict[str, Any] | None,
    style_sample: dict[str, Any] | None,
) -> PresetLayers:
    knowledges: list[str] = []
    relationships: list[str] = []

    for source in (bot_persona, style_sample):
        if not isinstance(source, dict):
            continue
        layers = source.get("layers")
        if isinstance(layers, dict):
            knowledges.extend(normalize_layer_lines(layers.get("knowledges")))
            relationships.extend(normalize_layer_lines(layers.get("relationships")))
        knowledges.extend(normalize_layer_lines(source.get("knowledges")))
        relationships.extend(normalize_layer_lines(source.get("relationships")))

    return PresetLayers(
        knowledges=normalize_layer_lines(knowledges),
        relationships=normalize_layer_lines(relationships),
    )
