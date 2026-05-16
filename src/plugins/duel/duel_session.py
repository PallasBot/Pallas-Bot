"""决斗群会话：双牛互见。"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from src.common.config import GroupConfig

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message
from src.plugins.duel.duel_message import message_plain_fingerprint

_PAIR_KEY = "duel_pair"
_IGNORE_KEY = "duel_narr_ignore"
_PAIR_TTL_SEC = 900


def _plain_fingerprint(text: str) -> str:
    t = re.sub(r"\[CQ:[^\]]+\]", "", text)
    return " ".join(t.split()).strip()[:120]


async def start_duel_pair(group_id: int, bot_a: int, bot_b: int) -> None:
    """登记群内决斗双牛，供 block 放行互见。"""
    gc = GroupConfig(group_id)
    pair = {"a": int(bot_a), "b": int(bot_b), "until": time.time() + _PAIR_TTL_SEC}
    await gc._update_in_memory(_PAIR_KEY, pair)
    await gc._update_in_memory(_IGNORE_KEY, [])


async def clear_duel_pair(group_id: int) -> None:
    gc = GroupConfig(group_id)
    await gc._update_in_memory(_PAIR_KEY, None)
    await gc._update_in_memory(_IGNORE_KEY, [])


async def get_duel_pair(group_id: int) -> tuple[int, int] | None:
    gc = GroupConfig(group_id)
    raw: Any = await gc._find_in_memory(_PAIR_KEY)
    if not isinstance(raw, dict):
        return None
    until = float(raw.get("until") or 0)
    if until < time.time():
        return None
    try:
        return int(raw["a"]), int(raw["b"])
    except (KeyError, TypeError, ValueError):
        return None


async def is_duel_paired_bot_traffic(group_id: int, sender_id: int, receiver_bot_id: int) -> bool:
    """决斗中的两只牛互相发言时不走「其他牛牛拦截」。"""
    pair = await get_duel_pair(group_id)
    if not pair:
        return False
    a, b = pair
    return sender_id in (a, b) and receiver_bot_id in (a, b) and sender_id != receiver_bot_id


async def register_duel_narrative_line(group_id: int, message: Message) -> None:
    """记入本群不复读学习的剧目指纹。"""
    fp = message_plain_fingerprint(message)
    if not fp:
        return
    gc = GroupConfig(group_id)
    lines: Any = await gc._find_in_memory(_IGNORE_KEY)
    if not isinstance(lines, list):
        lines = []
    if fp not in lines:
        lines.append(fp)
    if len(lines) > 80:
        lines = lines[-80:]
    await gc._update_in_memory(_IGNORE_KEY, lines)


async def should_skip_repeater_learn(group_id: int, user_id: int, raw_message: str) -> bool:
    """决斗台台词与参战牛消息不参与学习。"""
    pair = await get_duel_pair(group_id)
    if pair and user_id in pair:
        return True
    fp = _plain_fingerprint(raw_message)
    if not fp:
        return False
    gc = GroupConfig(group_id)
    lines: Any = await gc._find_in_memory(_IGNORE_KEY)
    if not isinstance(lines, list):
        return False
    return fp in lines
