"""load_plugin 前读 help 全局禁用名单。"""

from __future__ import annotations

import json
from functools import lru_cache

from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.storage.deploy_store import read_deploy_plugin_blob, write_deploy_plugin_blob

_BUILTIN_HELP_HIDDEN_PLUGINS = frozenset({
    "pb_webui",
    "pallas_webui",
    "pb_protocol",
    "pallas_protocol",
    "ingress_gate",
    "pb_stats",
    "relogin_forward",
    "maa_hub",
})

STARTUP_GLOBAL_DISABLE_PROTECTED = frozenset(sorted(_BUILTIN_HELP_HIDDEN_PLUGINS | frozenset({"help", "ingress_gate"})))

_FILE = "global_disabled_plugins.json"
_STORAGE_KEY = "global_disabled_plugins"
_PLUGIN = "help"


def _filter_protected(names: list[str]) -> frozenset[str]:
    protected = STARTUP_GLOBAL_DISABLE_PROTECTED
    return frozenset(x for x in names if x and x not in protected)


def _read_legacy_disabled() -> list[str]:
    path = plugin_data_dir(_PLUGIN) / _FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    vals = raw.get("disabled_plugins", [])
    if not isinstance(vals, list):
        return []
    return sorted({str(x).strip() for x in vals if str(x).strip()})


def _migrate_legacy_disabled() -> frozenset[str]:
    names = _read_legacy_disabled()
    legacy_path = plugin_data_dir(_PLUGIN) / _FILE
    if not names and not legacy_path.exists():
        return frozenset()
    blob = read_deploy_plugin_blob(_PLUGIN)
    blob[_STORAGE_KEY] = names
    write_deploy_plugin_blob(_PLUGIN, blob)
    if legacy_path.exists():
        backup = legacy_path.with_suffix(legacy_path.suffix + ".migrated")
        if not backup.exists():
            legacy_path.replace(backup)
    return _filter_protected(names)


@lru_cache(maxsize=1)
def startup_global_disabled_plugin_names() -> frozenset[str]:
    raw = read_deploy_plugin_blob(_PLUGIN).get(_STORAGE_KEY)
    if raw is None:
        return _migrate_legacy_disabled()
    if not isinstance(raw, list):
        return frozenset()
    names = sorted({str(x).strip() for x in raw if str(x).strip()})
    return _filter_protected(names)
