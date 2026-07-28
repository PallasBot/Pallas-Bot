"""聚合已加载插件的 plugin_storage 声明。"""

from __future__ import annotations

from operator import itemgetter
from typing import Any

from pallas.core.storage.metadata import PluginStorageDecl, iter_loaded_plugin_storage

_registry_cache: dict[tuple[str, str], PluginStorageDecl] | None = None


def clear_plugin_storage_registry_cache() -> None:
    global _registry_cache
    _registry_cache = None


def _storage_plugin_aliases(plugin_name: str) -> tuple[str, ...]:
    """NoneBot 加载名（如 pallas_plugin_draw）与短 id（draw）互相对齐。

    不经 ``plugin_identity``：该模块会绕进 console 形成循环导入。
    """
    name = (plugin_name or "").strip()
    if not name:
        return ()
    names: list[str] = [name]
    if name.startswith("pallas_plugin_"):
        short = name[len("pallas_plugin_") :]
        if short and short not in names:
            names.append(short)
    else:
        pip_mod = f"pallas_plugin_{name}"
        if pip_mod not in names:
            names.append(pip_mod)
    try:
        from pallas.core.platform.bot_runtime.plugin_matrix import (
            EXTRA_PACKAGE_MODULES,
            PLUGIN_LEGACY_ALIASES,
        )
    except Exception:
        return tuple(names)
    for plugin_id, aliases in PLUGIN_LEGACY_ALIASES.items():
        related = {plugin_id, *aliases}
        if name in related or any(n in related for n in names):
            for item in related:
                s = str(item or "").strip()
                if s and s not in names:
                    names.append(s)
    for modules in EXTRA_PACKAGE_MODULES.values():
        if name in modules or any(n in modules for n in names):
            for mod in modules:
                m = str(mod or "").strip()
                if m and m not in names:
                    names.append(m)
                if m.startswith("pallas_plugin_"):
                    short = m[len("pallas_plugin_") :]
                    if short and short not in names:
                        names.append(short)
    return tuple(names)


def _canonical_storage_plugin_name(plugin_name: str) -> str:
    name = (plugin_name or "").strip()
    if name.startswith("pallas_plugin_"):
        short = name[len("pallas_plugin_") :]
        if short:
            return short
    try:
        from pallas.core.platform.bot_runtime.plugin_matrix import PLUGIN_LEGACY_ALIASES

        for plugin_id, aliases in PLUGIN_LEGACY_ALIASES.items():
            if name == plugin_id or name in aliases:
                return plugin_id
    except Exception:
        pass
    return name


def merged_storage_registry() -> dict[tuple[str, str], PluginStorageDecl]:
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    merged: dict[tuple[str, str], PluginStorageDecl] = {}
    for plugin_name, _title, decl in iter_loaded_plugin_storage():
        for alias in _storage_plugin_aliases(plugin_name):
            merged.setdefault((alias, decl.key), decl)
    _registry_cache = merged
    return merged


def storage_decl_for(plugin_name: str, key: str) -> PluginStorageDecl | None:
    return merged_storage_registry().get((plugin_name.strip(), key.strip()))


def build_plugin_storage_ui() -> dict[str, Any]:
    plugins: dict[str, dict[str, Any]] = {}
    for plugin_name, title, decl in iter_loaded_plugin_storage():
        display_name = _canonical_storage_plugin_name(plugin_name)
        bucket = plugins.setdefault(
            display_name,
            {"plugin": display_name, "title": title, "keys": []},
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
