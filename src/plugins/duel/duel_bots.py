"""群内在线牛牛探测。"""

from __future__ import annotations

import random

from nonebot import get_bots

from src.plugins.block import plugin_config


async def list_group_online_bot_ids(group_id: int) -> list[int]:
    """当前进程已连接、且能查到本群资料的牛牛 QQ。"""
    bots = get_bots()
    out: list[int] = []
    for bid in sorted(plugin_config.bots):
        key = str(bid)
        if key not in bots:
            continue
        try:
            await bots[key].get_group_member_info(group_id=group_id, user_id=int(bid), no_cache=True)
        except Exception:
            continue
        out.append(int(bid))
    return out


async def pick_random_duel_bot_pair(group_id: int) -> tuple[int, int] | None:
    """随机两只在线牛，用于八角笼。"""
    ids = await list_group_online_bot_ids(group_id)
    if len(ids) < 2:
        return None
    a, b = random.sample(ids, 2)
    return a, b


def is_pallas_bot(qq: int | str) -> bool:
    return int(qq) in plugin_config.bots


def is_bot_qq(qq: str) -> bool:
    try:
        return int(qq) in plugin_config.bots
    except ValueError:
        return False
