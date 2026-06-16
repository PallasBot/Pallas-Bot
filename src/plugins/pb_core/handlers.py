"""pb_core 命令 handler。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import get_loaded_plugins

from src.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart
from src.console.cli.runtime_mode import resolve_bot_mode

if TYPE_CHECKING:
    from src.features.plugin_sdk import PluginHandlerContext

from .console import format_console_hint_text, format_plugins_summary_text
from .status import format_runtime_status_text
from .update import format_update_check_text


async def handle_status(ctx: PluginHandlerContext) -> None:
    await ctx.finish(format_runtime_status_text())


async def handle_console(ctx: PluginHandlerContext) -> None:
    await ctx.finish(format_console_hint_text())


async def handle_plugins(ctx: PluginHandlerContext) -> None:
    loaded = {p.name for p in get_loaded_plugins() if p.name}
    await ctx.finish(format_plugins_summary_text(loaded_names=loaded))


async def handle_update_check(ctx: PluginHandlerContext) -> None:
    await ctx.finish(await format_update_check_text())


async def handle_restart(ctx: PluginHandlerContext) -> None:
    if not bot_lifecycle_available():
        await ctx.finish("当前环境未检测到 run_unified_bot / run_sharded_bot，无法自动重启。")
        return
    mode = resolve_bot_mode("auto")
    scheduled = schedule_bot_restart(mode=mode, delay_s=3.0)
    if not scheduled:
        await ctx.finish("重启调度失败，请改用 WebUI 或 pallas restart。")
        return
    await ctx.finish(f"将在约 3 秒后重启（{mode}）。若未恢复请查看日志。")
