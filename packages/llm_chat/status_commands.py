"""超管私聊：查看 LLM 运行状态（不出现在用户帮助图）。"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, PrivateMessageEvent

from pallas.core.perm import private_message_permission_for_command
from pallas.product.llm.status import build_llm_status_text

status_cmd = on_command(
    "llm状态",
    aliases={"llm status", "LLM状态"},
    priority=5,
    block=True,
    permission=private_message_permission_for_command("llm_chat.status"),
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
