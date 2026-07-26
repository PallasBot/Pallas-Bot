"""LLM tool 覆写：描述 / hints / visibility（WebUI 可写）。"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Any

from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pathlib import Path

    from pallas.product.llm.tools.registry import LlmToolSpec

_lock = threading.Lock()
_cached_mtime: float | None = None
_cached_overrides: dict[str, dict[str, Any]] = {}


def overrides_file_path() -> Path:
    return plugin_data_dir("pb_webui", create=True) / "llm_tool_overrides.json"


def _parse_override_entry(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    description = str(value.get("description") or "").strip()
    if description:
        out["description"] = description
    raw_hints = value.get("hints")
    if isinstance(raw_hints, list):
        hints = [str(item).strip() for item in raw_hints if str(item).strip()]
        if hints:
            out["hints"] = hints
    visibility = str(value.get("visibility") or "").strip().lower()
    if visibility in {"visible", "deferred"}:
        out["visibility"] = visibility
    if "disabled" in value:
        out["disabled"] = bool(value.get("disabled"))
    return out or None


def load_tool_overrides() -> dict[str, dict[str, Any]]:
    global _cached_mtime, _cached_overrides  # noqa: PLW0603
    path = overrides_file_path()
    if not path.is_file():
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _cached_mtime == mtime:
            return dict(_cached_overrides)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _cached_mtime = mtime
            _cached_overrides = {}
            return {}
        if not isinstance(raw, dict):
            _cached_mtime = mtime
            _cached_overrides = {}
            return {}
        parsed: dict[str, dict[str, Any]] = {}
        for name, value in raw.items():
            tool_name = str(name or "").strip()
            if not tool_name:
                continue
            entry = _parse_override_entry(value)
            if entry:
                parsed[tool_name] = entry
        _cached_mtime = mtime
        _cached_overrides = parsed
        return dict(parsed)


def load_tool_description_overrides() -> dict[str, dict[str, str]]:
    """兼容旧调用方：仅返回含 description 的条目。"""
    out: dict[str, dict[str, str]] = {}
    for name, entry in load_tool_overrides().items():
        description = str(entry.get("description") or "").strip()
        if description:
            out[name] = {"description": description}
    return out


def save_tool_overrides(overrides: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """整表写入覆写文件；返回规范化后的内容。"""
    cleaned: dict[str, dict[str, Any]] = {}
    for name, value in (overrides or {}).items():
        tool_name = str(name or "").strip()
        if not tool_name:
            continue
        entry = _parse_override_entry(value)
        if entry:
            cleaned[tool_name] = entry
    path = overrides_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clear_tool_description_overrides_cache()
    return cleaned


def upsert_tool_override(tool_name: str, patch: dict[str, Any]) -> dict[str, Any]:
    name = str(tool_name or "").strip()
    if not name:
        raise ValueError("tool_name required")
    current = load_tool_overrides()
    merged = dict(current.get(name) or {})
    if "description" in patch:
        desc = str(patch.get("description") or "").strip()
        if desc:
            merged["description"] = desc
        else:
            merged.pop("description", None)
    if "hints" in patch:
        raw = patch.get("hints")
        if raw is None:
            merged.pop("hints", None)
        elif isinstance(raw, list):
            hints = [str(item).strip() for item in raw if str(item).strip()]
            if hints:
                merged["hints"] = hints
            else:
                merged.pop("hints", None)
    # 清理历史 willingness 键；口语统一走 hints
    merged.pop("willingness", None)
    if "visibility" in patch:
        vis = str(patch.get("visibility") or "").strip().lower()
        if vis in {"visible", "deferred"}:
            merged["visibility"] = vis
        elif not vis:
            merged.pop("visibility", None)
    if "disabled" in patch:
        if patch.get("disabled") is None:
            merged.pop("disabled", None)
        else:
            merged["disabled"] = bool(patch.get("disabled"))
    if merged:
        current[name] = merged
    else:
        current.pop(name, None)
    save_tool_overrides(current)
    return dict(merged)


def clear_tool_description_overrides_cache() -> None:
    global _cached_mtime, _cached_overrides  # noqa: PLW0603
    with _lock:
        _cached_mtime = None
        _cached_overrides = {}


def effective_tool_hints(spec: LlmToolSpec) -> frozenset[str]:
    base = frozenset(str(h).strip() for h in (getattr(spec, "hints", frozenset()) or frozenset()) if str(h).strip())
    override = load_tool_overrides().get(spec.name) or {}
    raw = override.get("hints")
    if isinstance(raw, list) and raw:
        return frozenset(str(item).strip() for item in raw if str(item).strip())
    return base


def effective_tool_visibility(spec: LlmToolSpec) -> str:
    override = load_tool_overrides().get(spec.name) or {}
    vis = str(override.get("visibility") or "").strip().lower()
    if vis in {"visible", "deferred"}:
        return vis
    return str(getattr(spec, "visibility", "visible") or "visible").strip().lower() or "visible"


def tool_override_disabled(tool_name: str) -> bool:
    override = load_tool_overrides().get(str(tool_name or "").strip()) or {}
    return bool(override.get("disabled"))
