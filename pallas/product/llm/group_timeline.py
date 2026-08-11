"""最近群消息的共享时间线上下文。"""

from __future__ import annotations

from pallas.core.foundation.db import Message, make_message_repository
from pallas.product.persona.prompt_guard import sanitize_prompt_block, sanitize_prompt_literal


def format_group_timeline(messages: list[Message]) -> str:
    """将已按时间排序的群消息压缩为带身份的 prompt 块。"""
    lines = ["【刚才的群聊】"]
    for message in messages:
        text = sanitize_prompt_literal(str(message.plain_text or ""), max_len=240)
        if not text:
            continue
        sender_name = sanitize_prompt_literal(str(message.sender_name or ""), max_len=40)
        speaker = sender_name or f"群友#{int(message.user_id) % 10000:04d}"
        message_id = int(message.message_id) if message.message_id is not None else 0
        prefix = f"[{message_id}] " if message_id > 0 else ""
        reply_to = int(message.reply_to_message_id) if message.reply_to_message_id is not None else 0
        reply = f" 回复 [{reply_to}]" if reply_to > 0 else ""
        lines.append(f"- {prefix}{speaker}{reply}：{text}")
    if len(lines) == 1:
        return ""
    return sanitize_prompt_block("\n".join(lines), max_len=2400)


async def build_recent_group_timeline(
    group_id: int,
    *,
    current_message_id: int | None,
    limit: int = 8,
) -> str:
    """读取当前消息之前最近的同群消息，不把当前消息重复注入。"""
    cap = max(1, min(int(limit), 16))
    messages = await make_message_repository().find_recent_in_group(int(group_id), limit=cap + 1)
    visible = [message for message in messages if message.message_id != current_message_id]
    return format_group_timeline(visible[-cap:])
