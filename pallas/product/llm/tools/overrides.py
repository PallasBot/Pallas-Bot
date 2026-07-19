"""LLM tool function 描述覆写（缩短 schema token）。"""

from __future__ import annotations

import json
import threading

from pallas.core.foundation.paths import plugin_data_dir

_lock = threading.Lock()
_cached_mtime: float | None = None
_cached_overrides: dict[str, dict[str, str]] = {}


def overrides_file_path():
    return plugin_data_dir("pb_webui", create=True) / "llm_tool_overrides.json"


def load_tool_description_overrides() -> dict[str, dict[str, str]]:
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
        parsed: dict[str, dict[str, str]] = {}
        for name, value in raw.items():
            tool_name = str(name or "").strip()
            if not tool_name or not isinstance(value, dict):
                continue
            description = str(value.get("description") or "").strip()
            if description:
                parsed[tool_name] = {"description": description}
        _cached_mtime = mtime
        _cached_overrides = parsed
        return dict(parsed)


def clear_tool_description_overrides_cache() -> None:
    global _cached_mtime, _cached_overrides  # noqa: PLW0603
    with _lock:
        _cached_mtime = None
        _cached_overrides = {}
