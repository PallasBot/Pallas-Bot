from __future__ import annotations

import json

from nonebot import get_plugin_config

from src.common.paths import plugin_data_dir

from .config import Config

_VISIBILITY_FILE = "help_visibility.json"


def _visibility_path():
    return plugin_data_dir("help") / _VISIBILITY_FILE


def resolve_help_ignored_plugins() -> list[str]:
    try:
        cfg = get_plugin_config(Config)
        vals = list(getattr(cfg, "ignored_plugins", []) or [])
    except Exception:
        vals = []
    return [str(x).strip() for x in vals if str(x).strip()]


def load_help_hidden_plugins() -> list[str]:
    path = _visibility_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    vals = raw.get("hidden_plugins", [])
    if not isinstance(vals, list):
        return []
    out = [str(x).strip() for x in vals if str(x).strip()]
    return sorted(set(out))


def save_help_hidden_plugins(hidden_plugins: list[str]) -> list[str]:
    out = sorted({str(x).strip() for x in hidden_plugins if str(x).strip()})
    path = _visibility_path()
    payload = {
        "hidden_plugins": out,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
