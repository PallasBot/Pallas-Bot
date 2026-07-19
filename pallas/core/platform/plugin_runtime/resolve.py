"""按插件槽位 ID 解析 NoneBot 已加载插件包内的子模块。"""

from __future__ import annotations

import importlib
import importlib.util
from typing import TYPE_CHECKING

from nonebot import get_loaded_plugins

if TYPE_CHECKING:
    from types import ModuleType


def plugin_identity(raw: str):
    from pallas.core.platform.plugin_runtime.plugin_identity import plugin_identity as resolve_plugin_identity

    return resolve_plugin_identity(raw)


def plugin_identity_or_none(raw: str):
    try:
        return plugin_identity(raw)
    except KeyError:
        return None


def loaded_plugin_module_prefix(plugin_id: str) -> str | None:
    target = (plugin_id or "").strip()
    if not target:
        return None
    target_identity = plugin_identity_or_none(target)
    for plugin in get_loaded_plugins():
        name = str(getattr(plugin, "name", "") or "").strip()
        mod = getattr(plugin, "module", None)
        module_name = getattr(mod, "__name__", "") if mod is not None else ""
        if name:
            ident = plugin_identity_or_none(name)
            if target_identity is not None and ident is not None:
                if ident.plugin_id == target_identity.plugin_id and module_name:
                    return module_name.strip()
            elif name == target and module_name:
                return module_name.strip()
        if module_name:
            ident = plugin_identity_or_none(module_name)
            if target_identity is not None and ident is not None:
                if ident.plugin_id == target_identity.plugin_id:
                    return module_name.strip()
            elif module_name == target or module_name.rsplit(".", 1)[-1] == target:
                return module_name.strip()
    return None


def import_plugin_submodule(plugin_id: str, submodule: str) -> ModuleType:
    """优先 loaded 插件包；否则回退 bundled ``src.plugins`` 或官方 pip 扩展模块。"""
    sub = (submodule or "").strip().lstrip(".")
    if not sub:
        raise ValueError("submodule must be non-empty")
    prefix = loaded_plugin_module_prefix(plugin_id)
    if prefix is None:
        prefix = bundled_or_extra_module_prefix(plugin_id)
    return importlib.import_module(f"{prefix}.{sub}")


def bundled_or_extra_module_prefix(plugin_id: str) -> str:
    raw = (plugin_id or "").strip()
    ident = plugin_identity_or_none(raw)
    bundled = ident.bundled_module_prefix if ident is not None else f"packages.{raw}"
    pip_prefix = ident.pip_module_prefix if ident is not None else None
    if bundled and importlib.util.find_spec(bundled) is not None:
        return bundled
    if pip_prefix and importlib.util.find_spec(pip_prefix) is not None:
        return pip_prefix
    return bundled or pip_prefix or (ident.plugin_id if ident is not None else raw)


def audit_plugin_submodule_targets(plugin_ids: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw_plugin_id in plugin_ids:
        ident = plugin_identity(raw_plugin_id)
        prefix = bundled_or_extra_module_prefix(ident.plugin_id)
        rows.append({
            "plugin_id": ident.plugin_id,
            "module_prefix": prefix,
            "ok": importlib.util.find_spec(prefix) is not None,
        })
    return rows
