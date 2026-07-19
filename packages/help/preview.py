"""帮助图 v3 预览与渲染编排。"""

from __future__ import annotations

from typing import Literal

from .draw_function_detail import draw_function_detail_image
from .draw_plugin_detail import draw_plugin_detail_image
from .draw_plugin_menu import draw_plugin_menu_image
from .menu_rows import build_help_menu_rows, paginate_menu_rows
from .plugin_detail_data import build_function_detail_data, build_plugin_detail_data
from .plugin_manager import find_plugin_by_identifier, is_plugin_disabled_for_help_display
from .renderer import render_v3_image_bytes
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
    if level == "menu":
        all_rows = await build_help_menu_rows(bot_id=bot_id, group_id=group_id, show_ignored=show_ignored)
        page_rows, current_page, total_pages = paginate_menu_rows(all_rows, page=page)
        enabled_count = sum(1 for row in all_rows if row.enabled)
        image = draw_plugin_menu_image(
            page_rows,
            show_ignored=show_ignored,
            page=current_page,
            total_pages=total_pages,
            total_plugin_count=len(all_rows),
            total_enabled_count=enabled_count,
        )
        cache_key = f"preview_menu|p={current_page}|tp={total_pages}|n={len(all_rows)}|ignored={int(show_ignored)}"
        return await render_v3_image_bytes(cache_key, image, group_id=group_id, style_name="menu_v1")

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
        data, issue = build_plugin_detail_data(resolved, plugin_enabled=not is_disabled)
        if data is None or issue.value != "ok":
            data, _ = build_plugin_detail_data("help", plugin_enabled=True)
        assert data is not None
        image = draw_plugin_detail_image(data)
        cache_key = f"preview_plugin|{resolved}|enabled={data.enabled}"
        return await render_v3_image_bytes(cache_key, image, group_id=group_id, style_name="detail_v1")

    func_id = (function or "1").strip() or "1"
    data, issue = build_function_detail_data(resolved, func_id)
    if data is None:
        data, _ = build_function_detail_data("help", "1")
    if data is None:
        raise ValueError("无法生成帮助预览")
    image = draw_function_detail_image(data)
    cache_key = f"preview_function|{resolved}|{func_id}|{data.index}"
    return await render_v3_image_bytes(cache_key, image, group_id=group_id, style_name="detail_v1")
