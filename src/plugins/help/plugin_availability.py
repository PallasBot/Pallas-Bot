"""帮助菜单：配置未启用的插件不进入总览。"""

from __future__ import annotations

import importlib

_CONFIG_GATED: dict[str, tuple[str, str, str]] = {
    "chat": ("src.plugins.chat.config", "get_chat_config", "chat_enable"),
    "sing": ("src.plugins.sing.config", "get_sing_config", "sing_enable"),
    "llm_chat": ("src.plugins.llm_chat.config", "get_llm_chat_config", "llm_chat_enable"),
    "ollama": ("src.plugins.llm_chat.config", "get_llm_chat_config", "llm_chat_enable"),
}

_avail_cache: dict[str, bool] | None = None


def invalidate_plugin_help_availability_cache() -> None:
    global _avail_cache
    _avail_cache = None


def is_plugin_help_available(plugin_name: str) -> bool:
    gate = _CONFIG_GATED.get((plugin_name or "").strip())
    if gate is None:
        return True
    global _avail_cache
    if _avail_cache is None:
        _avail_cache = {}
    cached = _avail_cache.get(plugin_name)
    if cached is not None:
        return cached
    module_path, getter_name, field = gate
    try:
        mod = importlib.import_module(module_path)
        getter = getattr(mod, getter_name)
        cfg = getter()
        result = bool(getattr(cfg, field, False))
    except Exception:
        result = False
    _avail_cache[plugin_name] = result
    return result
