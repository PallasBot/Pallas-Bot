from __future__ import annotations

import json
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir

_VISIBILITY_FILE = "help_visibility.json"
_STORAGE_KEY = "hidden_plugins"

BUILTIN_HELP_HIDDEN_PLUGINS = frozenset({
    "pb_webui",
    "pallas_webui",
    "pb_protocol",
    "pallas_protocol",
    "ingress_gate",
    "pb_stats",
    "relogin_forward",
    "maa_hub",
})


def _visibility_path():
    return plugin_data_dir("help") / _VISIBILITY_FILE


def _read_legacy_hidden_plugins() -> list[str]:
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
    return sorted({str(x).strip() for x in vals if str(x).strip()})


def _migrate_legacy_hidden_plugins() -> list[str]:
    legacy = _read_legacy_hidden_plugins()
    path = _visibility_path()
    if not legacy and not path.exists():
        return []
    from pallas.core.storage.deploy_store import DeployPluginStorage

    store = DeployPluginStorage("help")
    store.set(_STORAGE_KEY, legacy)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".migrated")
        if not backup.exists():
            path.replace(backup)
    return legacy


def _normalize_hidden_plugins(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return sorted({str(x).strip() for x in raw if str(x).strip()})


def load_help_hidden_plugins() -> list[str]:
    """从 deploy plugin_storage 读取的额外隐藏名单。"""
    try:
        from pallas.core.storage.deploy_store import DeployPluginStorage

        store = DeployPluginStorage("help")
        vals = store.get(_STORAGE_KEY)
        if vals is None:
            return _migrate_legacy_hidden_plugins()
        return _normalize_hidden_plugins(vals)
    except Exception:
        return _read_legacy_hidden_plugins()


def resolve_help_hidden_plugins() -> list[str]:
    """帮助总览与批量开关使用的完整隐藏名单。"""
    return sorted(BUILTIN_HELP_HIDDEN_PLUGINS | set(load_help_hidden_plugins()))


def save_help_hidden_plugins(hidden_plugins: list[str]) -> list[str]:
    out = sorted({str(x).strip() for x in hidden_plugins if str(x).strip()})
    from pallas.core.storage.deploy_store import DeployPluginStorage

    DeployPluginStorage("help").set(_STORAGE_KEY, out)
    return out


def resolve_console_stats_excluded_plugin_names() -> frozenset[str]:
    """控制台 Matcher 插件次数统计排除名单。"""
    names = set(BUILTIN_HELP_HIDDEN_PLUGINS)
    names.add("ingress_gate")
    return frozenset(str(n).strip().lower() for n in names if str(n).strip())


def resolve_help_ignored_plugins() -> list[str]:
    try:
        from .config import get_help_config

        cfg = get_help_config()
        vals = list(getattr(cfg, "ignored_plugins", []) or [])
    except Exception:
        vals = []
    return [str(x).strip() for x in vals if str(x).strip()]
