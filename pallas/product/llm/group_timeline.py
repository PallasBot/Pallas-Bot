"""最近群消息的共享时间线上下文。"""

from __future__ import annotations

from pallas.core.foundation.db import Message, make_message_repository
from pallas.product.llm.sender_identity import speaker_label
from pallas.product.persona.prompt_guard import sanitize_prompt_block, sanitize_prompt_literal


def format_group_timeline(messages: list[Message], *, self_bot_id: int | None = None) -> str:
    """将已按时间排序的群消息压缩为带身份的 prompt 块。

    去编号：不带 message_id / 引用 id，引用关系口语化成「（回X的话）」，
    让模型读起来像一段连续群聊，而不是日志摘录。
    bot 发言标注为本 bot / 其他 bot，不混进群友。
    """
    lines = ["【刚才的群聊】"]
    speaker_by_id: dict[int, str] = {}
    rendered: list[tuple[Message, str, str]] = []
    for message in messages:
        text = sanitize_prompt_literal(str(message.plain_text or ""), max_len=240)
        if not text:
            continue
        speaker = speaker_label(
            message.user_id,
            message.sender_name,
            self_bot_id=self_bot_id or 0,
        )
        message_id = int(message.message_id) if message.message_id is not None else 0
        if message_id > 0:
            speaker_by_id[message_id] = speaker
        rendered.append((message, speaker, text))
    for message, speaker, text in rendered:
        tail = ""
        reply_to = int(message.reply_to_message_id) if message.reply_to_message_id is not None else 0
        if reply_to > 0 and reply_to in speaker_by_id:
            tail = f"（回{speaker_by_id[reply_to]}的话）"
        lines.append(f"- {speaker}{tail}：{text}")
    if len(lines) == 1:
        return ""
    return sanitize_prompt_block("\n".join(lines), max_len=2400)


async def build_recent_group_timeline(
    group_id: int,
    *,
    current_message_id: int | None,
    limit: int = 8,
    self_bot_id: int | None = None,
) -> str:
    """读取当前消息之前最近的同群消息，不把当前消息重复注入。"""
    cap = max(1, min(int(limit), 16))
    messages = await make_message_repository().find_recent_in_group(int(group_id), limit=cap + 1)
    visible = [message for message in messages if message.message_id != current_message_id]
    return format_group_timeline(visible[-cap:], self_bot_id=self_bot_id)
