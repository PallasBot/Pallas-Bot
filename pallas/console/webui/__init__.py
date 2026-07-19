"""控制台 WebUI 共用能力：插件 ``.env`` 热重载、配置段注册、插件配置 API 辅助。"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

from .env_sections import (
    apply_webui_env_section_patch,
    clear_webui_env_sections_cache,
    field_to_env_uppercase_keys,
    get_webui_env_section,
    list_webui_env_sections,
    webui_env_section_payload,
)
from .plugin_api import apply_plugin_config_patch, plugin_config_payload
from .plugin_config import (
    PluginConfigProxy,
    PluginWebuiConfigHandle,
    config_from_env,
    default_parse_env_value,
    install_hot_reload_config,
    plugin_config_proxy,
)
from .registry import (
    PluginWebuiConfigHooks,
    read_plugin_config,
    register_plugin_webui_config,
    reload_plugin_config,
    resolve_plugin_webui_hooks,
    unregister_plugin_webui_config,
)

plugin_store_assets: ModuleType

__all__ = [
    "PluginConfigProxy",
    "PluginWebuiConfigHandle",
    "PluginWebuiConfigHooks",
    "apply_plugin_config_patch",
    "apply_webui_env_section_patch",
    "clear_webui_env_sections_cache",
    "config_from_env",
    "default_parse_env_value",
    "field_to_env_uppercase_keys",
    "get_webui_env_section",
    "install_hot_reload_config",
    "plugin_config_proxy",
    "plugin_store_assets",
    "list_webui_env_sections",
    "plugin_config_payload",
    "read_plugin_config",
    "register_plugin_webui_config",
    "reload_plugin_config",
    "resolve_plugin_webui_hooks",
    "unregister_plugin_webui_config",
    "webui_env_section_payload",
]


def __getattr__(name: str) -> Any:
    if name == "plugin_store_assets":
        module = importlib.import_module(".plugin_store_assets", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
