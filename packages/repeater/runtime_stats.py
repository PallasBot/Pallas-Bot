from __future__ import annotations

import time
from operator import itemgetter
from typing import Any

from .message_store import MessageStore
from .model import Chat


def repeater_runtime_cache_snapshot() -> dict[str, Any]:
    message_groups = MessageStore._message_dict
    reply_groups = Chat._reply_dict
    recent_topics = Chat._recent_topics

    message_group_rows = sorted(
        ((int(group_id), len(rows)) for group_id, rows in message_groups.items() if rows),
        key=itemgetter(1),
        reverse=True,
    )
    reply_group_rows = sorted(
        (
            (
                int(group_id),
                sum(len(rows) for rows in bot_rows.values()),
                len(bot_rows),
            )
            for group_id, bot_rows in reply_groups.items()
            if bot_rows
        ),
        key=itemgetter(1),
        reverse=True,
    )
    reply_max_bucket_records = max(
        (len(rows) for bot_rows in reply_groups.values() for rows in bot_rows.values()),
        default=0,
    )

    return {
        "message_groups": len(message_group_rows),
        "message_records": sum(size for _, size in message_group_rows),
        "message_max_group_records": max((size for _, size in message_group_rows), default=0),
        "reply_groups": len(reply_group_rows),
        "reply_bot_buckets": sum(bot_buckets for _, _, bot_buckets in reply_group_rows),
        "reply_records": sum(size for _, size, _ in reply_group_rows),
        "reply_max_bucket_records": reply_max_bucket_records,
        "recent_topics_groups": sum(1 for rows in recent_topics.values() if rows),
        "recent_topics_records": sum(len(rows) for rows in recent_topics.values()),
        "top_message_groups": [{"group_id": group_id, "records": size} for group_id, size in message_group_rows[:5]],
        "top_reply_groups": [
            {"group_id": group_id, "records": size, "bot_buckets": bot_buckets}
            for group_id, size, bot_buckets in reply_group_rows[:5]
        ],
    }


async def prune_repeater_runtime_caches(*, now: int | None = None, ttl_sec: int = 6 * 3600) -> dict[str, int]:
    cutoff = int(now if now is not None else time.time()) - max(60, int(ttl_sec))
    message_groups_removed = 0
    message_records_removed = 0
    active_message_groups: set[int] = set()

    async with MessageStore._message_lock:
        for group_id in list(MessageStore._message_dict):
            rows = MessageStore._message_dict.get(group_id) or []
            latest = max((int(getattr(row, "time", 0) or 0) for row in rows), default=0)
            if rows and latest >= cutoff:
                active_message_groups.add(int(group_id))
                continue
            message_groups_removed += 1
            message_records_removed += len(rows)
            MessageStore._message_dict.pop(group_id, None)

    reply_groups_removed = 0
    reply_bot_buckets_removed = 0
    reply_records_removed = 0
    active_reply_groups: set[int] = set()

    async with Chat._reply_lock:
        for group_id in list(Chat._reply_dict):
            bot_rows = Chat._reply_dict.get(group_id)
            if bot_rows is None:
                continue
            for bot_id in list(bot_rows):
                rows = bot_rows.get(bot_id) or []
                latest = max((int((row or {}).get("time") or 0) for row in rows), default=0)
                if rows and latest >= cutoff:
                    active_reply_groups.add(int(group_id))
                    continue
                reply_bot_buckets_removed += 1
                reply_records_removed += len(rows)
                bot_rows.pop(bot_id, None)
            if bot_rows:
                active_reply_groups.add(int(group_id))
                continue
            reply_groups_removed += 1
            Chat._reply_dict.pop(group_id, None)

    active_groups = active_message_groups | active_reply_groups
    recent_topics_groups_removed = 0
    async with Chat._topics_lock:
        for group_id in list(Chat._recent_topics):
            rows = Chat._recent_topics.get(group_id)
            if rows and int(group_id) in active_groups:
                continue
            recent_topics_groups_removed += 1
            Chat._recent_topics.pop(group_id, None)

    return {
        "message_groups_removed": message_groups_removed,
        "message_records_removed": message_records_removed,
        "reply_groups_removed": reply_groups_removed,
        "reply_bot_buckets_removed": reply_bot_buckets_removed,
        "reply_records_removed": reply_records_removed,
        "recent_topics_groups_removed": recent_topics_groups_removed,
    }
