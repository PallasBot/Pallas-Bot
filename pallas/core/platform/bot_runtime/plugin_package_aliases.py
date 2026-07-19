"""插件包名别名：统一委托到中心插件身份注册表。"""

from __future__ import annotations

from pallas.core.platform.plugin_runtime.plugin_identity import canonical_plugin_id
from pallas.core.platform.plugin_runtime.plugin_identity import plugin_identity as resolve_plugin_identity


def _build_plugin_package_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for raw in (
        "pallas_webui",
        "pallas_protocol",
        "community_stats",
        "pallas_plugin_community_stats",
        "ollama",
        "pallas_plugin_llm_chat",
    ):
        aliases[raw] = canonical_plugin_id(raw)
    for plugin_id in (
        "pb_core",
        "repeater",
        "help",
        "pb_webui",
        "request_handler",
        "blacklist",
        "drink",
        "greeting",
        "roulette",
        "take_name",
        "llm_chat",
        "pb_stats",
        "pb_protocol",
        "relogin_bot",
        "relogin_forward",
        "duel",
        "who_is_spy",
        "dream",
        "maa",
        "maa_hub",
        "draw",
        "sing",
        "chat",
        "bot_status",
    ):
        try:
            ident = resolve_plugin_identity(plugin_id)
        except KeyError:
            continue
        aliases[plugin_id] = ident.plugin_id
        for alias in ident.legacy_aliases:
            aliases[alias] = ident.plugin_id
        if ident.bundled_module_prefix:
            aliases[ident.bundled_module_prefix.rsplit(".", 1)[-1]] = ident.plugin_id
        if ident.pip_module_prefix:
            aliases[ident.pip_module_prefix] = ident.plugin_id
    return aliases


PLUGIN_PACKAGE_ALIASES: dict[str, str] = _build_plugin_package_aliases()


def canonical_plugin_package(name: str) -> str:
    return canonical_plugin_id(name)
