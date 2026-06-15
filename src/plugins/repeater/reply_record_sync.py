"""分片时广播牛牛回复缓存，供跨 worker 的「不可以」匹配。"""

from __future__ import annotations

from typing import Any

from src.platform.shard import context as shard_ctx
from src.plugins.repeater.model import Chat


def should_publish_reply_record(record: dict[str, Any]) -> bool:
    """占位符与空回复不参与跨片同步，减少无效 coord IO。"""
    reply = str(record.get("reply") or "").strip()
    if not reply:
        return False
    return reply not in {Chat.REPLY_FLAG, Chat.SPEAK_FLAG}


def publish_reply_record(group_id: int, bot_id: int, record: dict[str, Any]) -> None:
    if not should_publish_reply_record(record):
        return
    if not shard_ctx.sharding_active():
        return
    from src.platform.shard.coord.repeater_reply_buffer import schedule_publish_repeater_reply_record

    schedule_publish_repeater_reply_record(group_id, bot_id, record)
