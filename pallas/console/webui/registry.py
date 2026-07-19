"""WebUI 插件配置热重载注册表；由 ``install_hot_reload_config`` 自动登记。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ConfigGetter = Callable[[], Any]
ConfigReloader = Callable[[], None]


@dataclass(frozen=True)
class PluginWebuiConfigHooks:
    get: ConfigGetter
    reload: ConfigReloader
    clear_cache: Callable[[], None] | None = None


_registry: dict[str, PluginWebuiConfigHooks] = {}


def register_plugin_webui_config(module_key: str, hooks: PluginWebuiConfigHooks) -> None:
    key = (module_key or "").strip()
    if not key:
        raise ValueError("module_key 不能为空")
    _registry[key] = hooks


def unregister_plugin_webui_config(module_key: str) -> None:
    _registry.pop((module_key or "").strip(), None)


def _keys_for_plugin_module(module_name: str) -> tuple[str, ...]:
    name = (module_name or "").strip()
    if not name:
        return ()
    if name.endswith(".config"):
        plugin_mod = name[: -len(".config")]
        return (name, plugin_mod)
    return (f"{name}.config", name)


def resolve_plugin_webui_hooks(module_name: str) -> PluginWebuiConfigHooks | None:
    for key in _keys_for_plugin_module(module_name):
        hooks = _registry.get(key)
        if hooks is not None:
            return hooks
    return None


def read_plugin_config(module_name: str, cfg_cls: type, *, fallback_getter: ConfigGetter) -> Any:
    hooks = resolve_plugin_webui_hooks(module_name)
    if hooks is not None:
        return hooks.get()
    return fallback_getter()


def reload_plugin_config(module_name: str) -> bool:
    hooks = resolve_plugin_webui_hooks(module_name)
    if hooks is None:
        return False
    hooks.reload()
    return True
