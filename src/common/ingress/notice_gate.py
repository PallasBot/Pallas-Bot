"""Notice 入站门控：采样丢弃噪声 + 多号分片。"""

from __future__ import annotations

import random
import zlib

from nonebot import get_bots
from nonebot.adapters.onebot.v11 import NoticeEvent  # noqa: TC002

from src.common.ingress.config import get_ingress_config
from src.common.multi_bot import try_claim_cross_bot_message_memory

_NOTICE_PLUGIN = "ingress_notice"


def ingress_notice_gate_enabled() -> bool:
    return get_ingress_config().ingress_notice_gate_enabled


def notice_sample_keep_probability(notice_type: str, sub_type: str | None) -> float:
    cfg = get_ingress_config()
    if notice_type == "group_msg_emoji_like":
        return cfg.notice_emoji_like_keep
    if notice_type == "notify" and sub_type == "poke":
        return cfg.notice_poke_keep
    if notice_type == "group_recall":
        return cfg.notice_recall_keep
    return cfg.notice_default_keep


def should_sample_keep_notice(notice_type: str, sub_type: str | None) -> bool:
    prob = notice_sample_keep_probability(notice_type, sub_type)
    if prob >= 1.0:
        return True
    if prob <= 0.0:
        return False
    return random.random() < prob


def notice_shard_key(event: NoticeEvent) -> str | None:
    gid = getattr(event, "group_id", None)
    if not isinstance(gid, int) or gid <= 0:
        return None
    if event.notice_type == "group_msg_emoji_like":
        uid = getattr(event, "user_id", 0)
        mid = getattr(event, "message_id", 0)
        return f"emoji_like:{gid}:{uid}:{mid}"
    if event.notice_type == "notify" and getattr(event, "sub_type", None) == "poke":
        uid = getattr(event, "user_id", 0)
        tid = getattr(event, "target_id", 0)
        return f"poke:{gid}:{uid}:{tid}"
    return f"{event.notice_type}:{gid}:{getattr(event, 'user_id', 0)}"


def elect_notice_handler_bot(group_id: int, shard_key: str) -> int | None:
    bots = sorted(int(k) for k in get_bots().keys())
    if not bots:
        return None
    if len(bots) == 1:
        return bots[0]
    token = f"{group_id}:{shard_key}".encode()
    return bots[zlib.crc32(token) % len(bots)]


async def should_this_bot_handle_notice(bot_id: int, event: NoticeEvent) -> bool:
    if not ingress_notice_gate_enabled():
        return True
    gid = getattr(event, "group_id", None)
    if not isinstance(gid, int):
        return True
    key = notice_shard_key(event)
    if key is None:
        return True
    elected = elect_notice_handler_bot(gid, key)
    if elected is None:
        return True
    if int(bot_id) != elected:
        return False
    body = key
    uid = int(getattr(event, "user_id", 0) or 0)
    t = int(getattr(event, "time", 0) or 0)
    return await try_claim_cross_bot_message_memory(
        _NOTICE_PLUGIN,
        gid,
        uid,
        body,
        t,
        int(bot_id),
        use_plaintext=True,
    )


def classify_notice(event: NoticeEvent) -> tuple[str, str | None]:
    sub = getattr(event, "sub_type", None)
    return event.notice_type, sub if isinstance(sub, str) else None
