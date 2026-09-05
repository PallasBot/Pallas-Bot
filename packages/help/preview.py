"""帮助图 v3 预览与渲染编排。"""

from __future__ import annotations

from typing import Literal

from .menu_rows import build_help_menu_rows
from .plugin_detail_data import build_function_detail_data, build_plugin_detail_data
from .plugin_manager import find_plugin_by_identifier, is_plugin_disabled_for_help_display
from .renderer import render_function_detail_to_image, render_plugin_detail_to_image, render_plugin_menu_to_image
from .styles import load_config

PreviewLevel = Literal["menu", "plugin", "function"]


async def render_help_preview_bytes(
    *,
    level: PreviewLevel = "menu",
    page: int = 1,
    plugin: str | None = None,
    function: str | None = None,
    show_ignored: bool = False,
    bot_id: int | None = None,
    group_id: int | None = None,
) -> bytes:
    del page  # 总览不再分页；保留参数兼容旧预览 URL
    if level == "menu":
        all_rows = await build_help_menu_rows(bot_id=bot_id, group_id=group_id, show_ignored=show_ignored)
        enabled_count = sum(1 for row in all_rows if row.enabled)
        return await render_plugin_menu_to_image(
            all_rows,
            show_ignored=show_ignored,
            group_id=group_id,
            total_plugin_count=len(all_rows),
            total_enabled_count=enabled_count,
        )

    plugin_name = (plugin or "").strip() or "help"
    plugin_config = load_config()
    resolved, error = await find_plugin_by_identifier(
        plugin_name,
        None if show_ignored else (plugin_config.ignored_plugins if plugin_config else []),
    )
    if error or not resolved:
        resolved = plugin_name

    if level == "plugin":
        is_disabled = await is_plugin_disabled_for_help_display(
            resolved,
            group_id,
            bot_id,
            bot=None,
            event=None,
        )
        data, issue = build_plugin_detail_data(
            resolved,
            plugin_enabled=not is_disabled,
            show_ignored=show_ignored,
        )
        if data is None or issue.value != "ok":
            data, _ = build_plugin_detail_data("help", plugin_enabled=True, show_ignored=show_ignored)
        assert data is not None
        return await render_plugin_detail_to_image(data, group_id=group_id)

    func_id = (function or "1").strip() or "1"
    data, issue = build_function_detail_data(resolved, func_id, show_ignored=show_ignored)
    if data is None:
        data, _ = build_function_detail_data("help", "1", show_ignored=show_ignored)
    if data is None:
        raise ValueError("无法生成帮助预览")
    return await render_function_detail_to_image(data, group_id=group_id)
