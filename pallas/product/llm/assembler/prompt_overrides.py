"""Bot+群范围的 Prompt 分段覆盖存储与应用规则。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.paths import plugin_data_dir
from pallas.product.persona.prompt_guard import sanitize_prompt_block

if TYPE_CHECKING:
    from pathlib import Path

OverrideMode = Literal["replace", "append", "disable"]
PromptSectionOverride = dict[str, str]

MAX_OVERRIDE_CONTENT_LENGTH = 12_000


def prompt_overrides_path() -> Path:
    return plugin_data_dir("pb_webui") / "prompt_section_overrides.json"


def _load_state() -> dict[str, Any]:
    try:
        raw = json.loads(prompt_overrides_path().read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {"version": 1, "scopes": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("scopes"), dict):
        return {"version": 1, "scopes": {}}
    return {"version": 1, "scopes": raw["scopes"]}


def _scope_key(bot_id: int, group_id: int) -> str:
    return f"{bot_id}:{group_id}"


def _normalise_sections(sections: Mapping[str, Any]) -> dict[str, PromptSectionOverride]:
    normalised: dict[str, PromptSectionOverride] = {}
    for section_id, value in sections.items():
        if not isinstance(section_id, str) or not section_id.strip():
            continue
        if isinstance(value, Mapping):
            mode = value.get("mode")
            content = value.get("content", "")
        else:
            mode = getattr(value, "mode", None)
            content = getattr(value, "content", "")
        if mode not in {"replace", "append", "disable"} or not isinstance(content, str):
            continue
        normalised[section_id] = {
            "mode": mode,
            "content": sanitize_prompt_block(content, max_len=MAX_OVERRIDE_CONTENT_LENGTH),
        }
    return normalised


def load_prompt_overrides(*, bot_id: int, group_id: int) -> dict[str, PromptSectionOverride]:
    state = _load_state()
    scope = state["scopes"].get(_scope_key(bot_id, group_id))
    if not isinstance(scope, Mapping):
        return {}
    sections = scope.get("sections")
    return _normalise_sections(sections) if isinstance(sections, Mapping) else {}


def save_prompt_overrides(
    *, bot_id: int, group_id: int, sections: Mapping[str, Any]
) -> dict[str, PromptSectionOverride]:
    if bot_id < 1 or group_id < 1:
        raise ValueError("bot_id and group_id must be positive integers")
    normalised = _normalise_sections(sections)
    path = prompt_overrides_path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        state = _load_state()
        scope_key = _scope_key(bot_id, group_id)
        current_scope = state["scopes"].get(scope_key)
        current_sections = current_scope.get("sections") if isinstance(current_scope, Mapping) else {}
        merged = _normalise_sections(current_sections) if isinstance(current_sections, Mapping) else {}
        merged.update(normalised)
        state["scopes"][scope_key] = {"sections": merged}
        atomic_write_text(path, json.dumps(state, ensure_ascii=False, separators=(",", ":")))
    return merged


def apply_prompt_section_overrides(
    section_ids: tuple[str, ...],
    sections: list[str],
    overrides: Mapping[str, Mapping[str, Any]] | None,
) -> list[str]:
    if not overrides:
        return sections
    applied: list[str] = []
    for section_id, content in zip(section_ids, sections, strict=True):
        override = overrides.get(section_id)
        if not isinstance(override, Mapping):
            applied.append(content)
            continue
        mode = override.get("mode")
        replacement = override.get("content", "")
        if not isinstance(replacement, str):
            applied.append(content)
            continue
        replacement = sanitize_prompt_block(replacement, max_len=MAX_OVERRIDE_CONTENT_LENGTH)
        if mode == "disable":
            applied.append("")
        elif mode == "replace":
            applied.append(replacement)
        elif mode == "append":
            applied.append("\n\n".join(part for part in (content, replacement) if part))
        else:
            applied.append(content)
    return applied
