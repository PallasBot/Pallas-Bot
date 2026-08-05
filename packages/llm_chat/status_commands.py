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
    "牛牛测试缓存表情",
    priority=5,
    block=True,
    permission=group_message_permission_for_command("llm_chat.sticker_test"),
)

llm_sticker_test_cmd = on_command(
    "牛牛测试LLM表情",
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


async def run_sticker_test(bot, event: GroupMessageEvent) -> str | None:
    sent = await send_cached_sticker_image(bot, int(event.group_id))
    return None if sent else "没有可发送的 Repeater 缓存表情图。"


async def run_llm_sticker_test(bot, event: GroupMessageEvent) -> str | None:
    text = str(event.get_plaintext() or "").removeprefix("牛牛测试LLM表情").strip()
    if not text:
        return "请在命令后附上待匹配的文本。"
    from pallas.core.shared.utils.media_cache import get_recent_images
    from pallas.product.llm.sticker_vision import enqueue_sticker_vision_job

    candidates = await get_recent_images(4)
    if len(candidates) < 3:
        return "没有足够的缓存表情图供 LLM 选择。"
    fallback = candidates[0][0]
    await enqueue_sticker_vision_job(
        candidates,
        user_text=text,
        timeout_sec=8.0,
        idempotency_key=f"sticker_vision.test:{int(bot.self_id)}:{int(event.group_id)}:{int(event.message_id)}",
        bot_id=int(bot.self_id),
        group_id=int(event.group_id),
        fallback_cq_code=fallback,
    )
    return None


@sticker_test_cmd.handle()
async def handle_sticker_test(bot, event: MessageEvent) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    response = await run_sticker_test(bot, event)
    if response:
        await sticker_test_cmd.finish(response)


@llm_sticker_test_cmd.handle()
async def handle_llm_sticker_test(bot, event: MessageEvent) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    response = await run_llm_sticker_test(bot, event)
    if response:
        await llm_sticker_test_cmd.finish(response)
