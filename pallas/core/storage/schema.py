"""聚合已加载插件的 plugin_storage 声明。"""

from __future__ import annotations

from operator import itemgetter
from typing import Any

from pallas.core.storage.metadata import PluginStorageDecl, iter_loaded_plugin_storage

_registry_cache: dict[tuple[str, str], PluginStorageDecl] | None = None


def clear_plugin_storage_registry_cache() -> None:
    global _registry_cache
    _registry_cache = None


def merged_storage_registry() -> dict[tuple[str, str], PluginStorageDecl]:
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    merged: dict[tuple[str, str], PluginStorageDecl] = {}
    for plugin_name, _title, decl in iter_loaded_plugin_storage():
        merged[(plugin_name, decl.key)] = decl
    _registry_cache = merged
    return merged


def storage_decl_for(plugin_name: str, key: str) -> PluginStorageDecl | None:
    return merged_storage_registry().get((plugin_name.strip(), key.strip()))


def build_plugin_storage_ui() -> dict[str, Any]:
    plugins: dict[str, dict[str, Any]] = {}
    for plugin_name, title, decl in iter_loaded_plugin_storage():
        bucket = plugins.setdefault(
            plugin_name,
            {"plugin": plugin_name, "title": title, "keys": []},
        )
        bucket["keys"].append({
            "key": decl.key,
            "scope": decl.scope,
            "label": decl.label or decl.key,
            "ephemeral": decl.ephemeral,
        })
    rows = list(plugins.values())
    for row in rows:
        row["keys"].sort(key=itemgetter("key"))
    rows.sort(key=itemgetter("plugin"))
    return {"plugins": rows}
