"""用当前仓库已加载插件渲染生产向帮助图预览 → tmp/help_prod_*.png。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pallas.core.foundation.config.dotenv import apply_repo_settings_to_environ

apply_repo_settings_to_environ()

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()
    nonebot.get_driver().register_adapter(ONEBOT_V11Adapter)

from pallas.core.platform.bot_runtime import load_plugins_for_role

load_plugins_for_role()

from packages.help.draw_function_detail import draw_function_detail_image  # noqa: E402
from packages.help.draw_plugin_detail import draw_plugin_detail_image  # noqa: E402
from packages.help.draw_plugin_menu import draw_plugin_menu_image  # noqa: E402
from packages.help.help_theme import set_help_visual_mode  # noqa: E402
from packages.help.menu_rows import build_help_menu_rows, paginate_menu_rows  # noqa: E402
from packages.help.plugin_detail_data import (  # noqa: E402
    build_function_detail_data,
    build_plugin_detail_data,
)
from packages.help.plugin_manager import plugin_display_name  # noqa: E402


def pick_plugin_for_detail(rows) -> str:
    """优先带功能菜单的常见插件，否则取第一行。"""
    preferred = ("chat", "help", "pb_core", "roulette", "drink", "tools")
    by_name = {str(getattr(r.plugin, "name", "") or ""): r for r in rows}
    for name in preferred:
        if name in by_name:
            data, _ = build_plugin_detail_data(name, plugin_enabled=by_name[name].enabled)
            if data is not None and data.functions:
                return name
    for row in rows:
        name = str(getattr(row.plugin, "name", "") or "")
        if not name:
            continue
        data, _ = build_plugin_detail_data(name, plugin_enabled=row.enabled)
        if data is not None and data.functions:
            return name
    return str(getattr(rows[0].plugin, "name", "") or "help") if rows else "help"


async def main() -> None:
    out_dir = ROOT / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    set_help_visual_mode("light")

    all_rows = await build_help_menu_rows(bot_id=None, group_id=None, show_ignored=False)
    if not all_rows:
        raise SystemExit("未加载到可展示的帮助插件，请检查 load_plugins_for_role")

    page_rows, page, total_pages = paginate_menu_rows(all_rows, page=1)
    enabled_count = sum(1 for row in all_rows if row.enabled)
    menu = draw_plugin_menu_image(
        page_rows,
        show_ignored=False,
        page=page,
        total_pages=total_pages,
        total_plugin_count=len(all_rows),
        total_enabled_count=enabled_count,
    )
    menu_path = out_dir / "help_prod_menu.png"
    menu.save(menu_path)
    print(f"menu plugins={len(all_rows)} page={page}/{total_pages} -> {menu_path}")
    for row in page_rows[:12]:
        print(f"  {row.index}. {row.display_name} [{row.help_tag}] {'开' if row.enabled else '关'}")

    plugin_name = pick_plugin_for_detail(all_rows)
    enabled = next((r.enabled for r in all_rows if getattr(r.plugin, "name", None) == plugin_name), True)
    plugin_data, issue = build_plugin_detail_data(plugin_name, plugin_enabled=enabled)
    if plugin_data is None:
        raise SystemExit(f"无法构建插件详情: {plugin_name} issue={issue}")
    plugin_img = draw_plugin_detail_image(plugin_data)
    plugin_path = out_dir / "help_prod_plugin.png"
    plugin_img.save(plugin_path)
    print(f"plugin {plugin_display_name(plugin_data.plugin)} funcs={len(plugin_data.functions)} -> {plugin_path}")

    func_data = None
    if plugin_data.functions:
        func_data, _ = build_function_detail_data(plugin_name, "1")
    if func_data is None:
        func_data, _ = build_function_detail_data("help", "1")
    if func_data is None:
        raise SystemExit("无法构建功能详情")
    function_img = draw_function_detail_image(func_data)
    function_path = out_dir / "help_prod_function.png"
    function_img.save(function_path)
    print(f"function {func_data.display_name}/{func_data.func_name} -> {function_path}")

    # 若总览超过一页，再出第 2 页便于对照生产分页
    if total_pages > 1:
        page2_rows, page2, _ = paginate_menu_rows(all_rows, page=2)
        menu2 = draw_plugin_menu_image(
            page2_rows,
            show_ignored=False,
            page=page2,
            total_pages=total_pages,
            total_plugin_count=len(all_rows),
            total_enabled_count=enabled_count,
        )
        menu2_path = out_dir / "help_prod_menu_p2.png"
        menu2.save(menu2_path)
        print(f"menu page2 -> {menu2_path}")


if __name__ == "__main__":
    asyncio.run(main())
