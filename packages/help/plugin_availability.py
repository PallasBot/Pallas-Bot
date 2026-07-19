"""帮助菜单：配置未启用的插件不进入总览。"""

from __future__ import annotations

import importlib

_CONFIG_GATED: dict[str, tuple[str, str, str]] = {
    "chat": ("pallas.product.llm.config", "get_llm_config", "llm_chat_enabled"),
    "sing": ("packages.sing.config", "get_sing_config", "sing_enable"),
    "llm_chat": ("pallas.product.llm.config", "get_llm_config", "llm_chat_enabled"),
    "ollama": ("pallas.product.llm.config", "get_llm_config", "llm_chat_enabled"),
}

_avail_cache: dict[str, bool] | None = None


def invalidate_plugin_help_availability_cache() -> None:
    global _avail_cache
    _avail_cache = None


def is_plugin_help_available(plugin_name: str) -> bool:
    name = (plugin_name or "").strip()
    if name == "chat":
        from pallas.product.llm.availability import is_drunk_chat_enabled

        return is_drunk_chat_enabled()
    gate = _CONFIG_GATED.get(name)
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
    if result and name in {"llm_chat", "ollama"}:
        from pallas.product.llm.startup_probe import llm_ai_service_reachable

        reachable = llm_ai_service_reachable()
        if reachable is False:
            result = False
    _avail_cache[plugin_name] = result
    return result
