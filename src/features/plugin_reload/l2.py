"""L2 元数据热重载：重建 help / ingress 索引（不卸载 matcher）。"""

from __future__ import annotations

from nonebot import get_loaded_plugins, logger
from nonebot.plugin import PluginMetadata

from src.features.plugin_reload.metadata import ReloadPolicy, reload_policy_from_metadata


def reload_plugin_metadata_l2() -> None:
    """重建由 PluginMetadata.extra 派生的运行时索引。"""
    from src.features.cmd_perm.schema import clear_merged_defaults_cache
    from src.features.plugin_storage.schema import clear_plugin_storage_registry_cache
    from src.platform.ingress.plugin_command_plaintext import clear_plugin_command_plaintext_cache
    from src.plugins.help.plugin_manager import clear_help_cache

    clear_plugin_command_plaintext_cache()
    clear_plugin_storage_registry_cache()
    clear_merged_defaults_cache()
    clear_help_cache()
    logger.info("plugin metadata L2 reload: ingress/help/storage 索引已重建")


def reload_policy_for_plugin_name(plugin_name: str) -> ReloadPolicy:
    name = (plugin_name or "").strip()
    if not name:
        return "config_only"
    for plugin in get_loaded_plugins():
        if str(getattr(plugin, "name", "") or "").strip() == name:
            meta = getattr(plugin, "metadata", None)
            if isinstance(meta, PluginMetadata):
                return reload_policy_from_metadata(meta)
            return reload_policy_from_metadata(None)
    return "config_only"


def reload_metadata_after_plugin_config_save(plugin_name: str) -> bool:
    """WebUI 插件配置保存后：``metadata`` / ``full`` 策略触发 L2 索引重建。"""
    policy = reload_policy_for_plugin_name(plugin_name)
    if policy not in ("metadata", "full"):
        return False
    if policy == "full":
        logger.debug(
            "plugin {} 声明 reload_policy=full，L3 代码重载未实现，已仅执行 L2 索引重建",
            plugin_name,
        )
    reload_plugin_metadata_l2()
    return True
