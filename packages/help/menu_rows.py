"""一级帮助菜单行数据。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .help_constants import HELP_STATUS_OFF, HELP_STATUS_ON
from .help_tags import DEFAULT_HELP_TAG, resolve_help_tag_overrides, resolve_plugin_help_tag
from .plugin_manager import (
    collect_disabled_plugin_names,
    get_help_menu_plugins,
    plugin_display_name,
    resolve_plugin_disable_scope,
)
from .styles import load_config


@dataclass(frozen=True, slots=True)
class HelpMenuRow:
    index: int
    plugin: Any
    display_name: str
    description: str
    enabled: bool
    help_tag: str = DEFAULT_HELP_TAG


async def build_help_menu_rows(
    *,
    bot_id: int | None,
    group_id: int | None,
    show_ignored: bool,
) -> list[HelpMenuRow]:
    plugin_config = load_config()
    plugins = get_help_menu_plugins(
        show_ignored=show_ignored,
        ignored_plugins=None if show_ignored else (plugin_config.ignored_plugins if plugin_config else []),
    )
    disabled_names = await collect_disabled_plugin_names(bot_id, group_id, ignore_cache=False)
    bot_disabled_names = (
        await collect_disabled_plugin_names(bot_id, None, ignore_cache=False) if group_id else disabled_names
    )
    tag_overrides = resolve_help_tag_overrides()

    rows: list[HelpMenuRow] = []
    for index, plugin in enumerate(plugins, 1):
        plugin_name = plugin.name or "未命名插件"
        names = bot_disabled_names if resolve_plugin_disable_scope(plugin_name) == "bot" else disabled_names
        enabled = plugin_name not in names
        meta = getattr(plugin, "metadata", None)
        description = "暂无描述"
        if meta is not None:
            description = getattr(meta, "description", None) or description
        rows.append(
            HelpMenuRow(
                index=index,
                plugin=plugin,
                display_name=plugin_display_name(plugin),
                description=str(description).strip() or "暂无描述",
                enabled=enabled,
                help_tag=resolve_plugin_help_tag(plugin, overrides=tag_overrides),
            )
        )
    return rows


def status_label(enabled: bool) -> str:
    return HELP_STATUS_ON if enabled else HELP_STATUS_OFF
