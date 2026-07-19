from __future__ import annotations

from nonebot import get_loaded_plugins, logger
from nonebot.plugin import PluginMetadata

from pallas.core.plugin_reload.metadata import ReloadPolicy, reload_policy_from_metadata


def reload_plugin_metadata_index() -> None:
    from packages.help.plugin_manager import clear_help_cache
    from pallas.core.perm.schema import clear_merged_defaults_cache
    from pallas.core.platform.ingress.plugin_command_plaintext import clear_plugin_command_plaintext_cache
    from pallas.core.storage.schema import clear_plugin_storage_registry_cache

    clear_plugin_command_plaintext_cache()
    clear_plugin_storage_registry_cache()
    clear_merged_defaults_cache()
    clear_help_cache()
    logger.info("plugin metadata index reload: ingress/help/storage 索引已重建")


def reload_policy_for_plugin_name(plugin_name: str) -> ReloadPolicy:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    name = canonical_plugin_package((plugin_name or "").strip())
    if not name:
        return "config_only"
    for plugin in get_loaded_plugins():
        pkg = canonical_plugin_package(str(getattr(plugin, "name", "") or "").strip())
        if pkg == name:
            meta = getattr(plugin, "metadata", None)
            if isinstance(meta, PluginMetadata):
                return reload_policy_from_metadata(meta)
            return reload_policy_from_metadata(None)
    return "config_only"


def reload_metadata_after_plugin_config_save(plugin_name: str) -> bool:
    policy = reload_policy_for_plugin_name(plugin_name)
    if policy not in ("metadata", "full"):
        return False
    if policy == "full":
        logger.debug(
            "plugin {} 声明 reload_policy=full，代码级重载未实现，已仅执行元数据索引重建",
            plugin_name,
        )
    reload_plugin_metadata_index()
    return True
