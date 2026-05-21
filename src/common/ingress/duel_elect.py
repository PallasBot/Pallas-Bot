"""入站分片与牛牛决斗主持牛对齐（与 plugins.duel 规则一致）。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent


async def ingress_duel_elected_bot_id(event: GroupMessageEvent) -> int | None:
    """若返回 bot QQ，仅该连接应通过入站分片；None 表示改走 duel/ingress claim 抢占。"""
    from src.plugins.duel.duel_bots import (
        duel_narrator_bot_id,
        infer_duel_defender_when_at_self_hidden,
        is_bot_qq,
        is_cage_plaintext,
        parse_duel_at_qqs,
        pick_cage_duel_bot_pair,
    )

    plain = event.get_plaintext().strip()

    if is_cage_plaintext(plain):
        pair = await pick_cage_duel_bot_pair(
            int(event.group_id),
            int(event.user_id),
            int(event.time),
        )
        if pair is not None:
            return min(pair[0], pair[1])
        return None

    if not plain.startswith("牛牛决斗"):
        return None

    ats = parse_duel_at_qqs(event)
    if len(ats) == 0:
        inferred = infer_duel_defender_when_at_self_hidden(event)
        if inferred:
            ats = [inferred]

    if len(ats) >= 2 and is_bot_qq(ats[0]) and is_bot_qq(ats[1]):
        return min(int(ats[0]), int(ats[1]))

    if len(ats) != 1:
        return None

    defender = ats[0]
    match = re.search(r"user_id=(\d+)", str(event.sender))
    if not match:
        return None
    challenger = match.group(1)
    return duel_narrator_bot_id(challenger, defender, dual_bot=False)


def ingress_message_uses_duel_claim(event: GroupMessageEvent) -> bool:
    """人 vs 人等无固定主持牛时，与插件 claim(\"duel\") 保持一致。"""
    from src.plugins.duel.duel_bots import is_cage_plaintext

    plain = event.get_plaintext().strip()
    if plain == "决斗事件重载":
        return True
    if is_cage_plaintext(plain):
        return True
    if plain.startswith("牛牛决斗"):
        return True
    return False
