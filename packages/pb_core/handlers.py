"""pb_core 命令 handler。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import get_loaded_plugins

from pallas.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart
from pallas.console.cli.runtime_mode import resolve_bot_mode

if TYPE_CHECKING:
    from pallas.core.commands import PluginHandlerContext

from .admins import (
    ADD_BOT_ADMIN_COMMAND,
    add_bot_admins,
    format_add_bot_admin_result,
    parse_add_bot_admin_targets,
)
from .console import format_console_hint_text, format_plugins_summary_text
from .restart_notify import record_restart_notify
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


async def handle_add_bot_admin(ctx: PluginHandlerContext) -> None:
    parsed = parse_add_bot_admin_targets(
        ctx.plain_text,
        ctx.event.message,
        self_id=int(ctx.event.self_id),
    )
    if parsed is None:
        await ctx.finish(
            f"用法：{ADD_BOT_ADMIN_COMMAND} 号主QQ [号主QQ…] [牛 目标牛QQ]\n"
            "默认加到当前私聊的牛；要配置别的牛时带「牛 目标牛QQ」。也可 @ 号主。"
        )
        return
    bot_id, admin_ids = parsed
    created, merged, added = await add_bot_admins(bot_id, admin_ids)
    await ctx.finish(
        format_add_bot_admin_result(
            bot_id=bot_id,
            created=created,
            merged=merged,
            added=added,
        )
    )


async def handle_restart(ctx: PluginHandlerContext) -> None:
    if not bot_lifecycle_available():
        await ctx.finish("当前环境未检测到 run_unified_bot / run_sharded_bot，无法自动重启。")
        return
    mode = resolve_bot_mode("auto")
    record_restart_notify(
        user_id=int(ctx.user_id),
        bot_id=int(ctx.event.self_id),
        mode=mode,
    )
    scheduled = schedule_bot_restart(mode=mode, delay_s=3.0)
    if not scheduled:
        await ctx.finish("重启调度失败，请改用 WebUI 或 pallas restart。")
        return
    await ctx.finish(f"将在约 3 秒后重启（{mode}）。恢复后会私聊通知你。")
