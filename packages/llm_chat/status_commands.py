"""超管私聊：查看 LLM 运行状态（不出现在用户帮助图）。"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, PrivateMessageEvent

from pallas.api.perm import group_message_permission_for_command, private_message_permission_for_command
from pallas.product.llm.delivery import send_cached_sticker_image
from pallas.product.llm.runtime_api import build_llm_status_text

status_cmd = on_command(
    "llm状态",
    aliases={"llm status", "LLM状态"},
    priority=5,
    block=True,
    permission=private_message_permission_for_command("llm_chat.status"),
)

sticker_test_cmd = on_command(
    "牛牛测试表情",
    priority=5,
    block=True,
    permission=group_message_permission_for_command("llm_chat.sticker_test"),
)


@status_cmd.handle()
async def handle_llm_status(event: MessageEvent) -> None:
    if not isinstance(event, PrivateMessageEvent):
        return
    try:
        text = await build_llm_status_text()
    except Exception as exc:
        await status_cmd.finish(f"读取 LLM 状态失败：{exc}")
        return
    await status_cmd.finish(text)


async def run_sticker_test(bot, event: GroupMessageEvent) -> str:
    sent = await send_cached_sticker_image(bot, int(event.group_id))
    return "已发送一张 Repeater 缓存表情图。" if sent else "没有可发送的 Repeater 缓存表情图。"


@sticker_test_cmd.handle()
async def handle_sticker_test(bot, event: MessageEvent) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    await sticker_test_cmd.finish(await run_sticker_test(bot, event))
