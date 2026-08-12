"""群管命令：重置本 bot 在本群的表达风格学习数据。"""

from __future__ import annotations

from nonebot import logger

from pallas.api.commands import PluginHandlerContext, bind_alias_handlers, group_command
from pallas.api.logging import format_plugin_event
from pallas.product.llm.repeater_semantic_style import clear_semantic_style_data

reset_style_cmd = group_command(
    "llm_chat.reset_style",
    "重置表达",
    aliases=("重置群表达", "清空表达风格"),
    block=True,
)


def clear_group_style_for(bot_id: int, group_id: int) -> int:
    """清空指定 bot 在指定群的表达风格，返回移除的示例条数。"""
    status = clear_semantic_style_data(bot_id=int(bot_id), group_id=int(group_id))
    return int(status.get("example_count") or 0)


async def handle_reset_group_style(ctx: PluginHandlerContext) -> None:
    bot_id = int(ctx.bot.self_id)
    group_id = int(ctx.group_id) if ctx.group_id is not None else 0
    if not bot_id or not group_id:
        return
    removed = clear_group_style_for(bot_id, group_id)
    await ctx.matcher.send(f"已清空本牛在本群的表达风格记录（{removed} 条示例），会重新学习。")
    logger.info(
        format_plugin_event(
            "reset_group_style",
            f"Bot [{bot_id}] cleared group expression style in group [{group_id}] ({removed} examples)",
        )
    )


bind_alias_handlers(reset_style_cmd, handle_reset_group_style)
