"""决斗双方展示名：叙事用群名片/昵称，开战时解析并放入上下文。"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

DISPLAY_NAME_MAX_LEN = 24


@dataclass(frozen=True)
class DuelLabels:
    challenger_id: str
    defender_id: str
    challenger_name: str
    defender_name: str

    def name_for(self, qq: str | int) -> str:
        uid = str(qq)
        if uid == self.challenger_id:
            return self.challenger_name
        if uid == self.defender_id:
            return self.defender_name
        return uid


_duel_labels: ContextVar[DuelLabels | None] = ContextVar("_duel_labels", default=None)


def bind_duel_labels(labels: DuelLabels) -> Token:
    return _duel_labels.set(labels)


def reset_duel_labels(token: Token) -> None:
    _duel_labels.reset(token)


def duel_label_for(qq: str | int) -> str:
    labels = _duel_labels.get()
    if labels is None:
        return str(qq)
    return labels.name_for(qq)


async def fetch_group_member_display_name(
    bot: Any,
    group_id: int,
    user_id: str | int,
) -> str:
    try:
        info = await bot.get_group_member_info(
            group_id=int(group_id),
            user_id=int(user_id),
            no_cache=True,
        )
        name = (info.get("card") or info.get("nickname") or "").strip()
        if name:
            return name[:DISPLAY_NAME_MAX_LEN]
    except Exception:
        pass
    return str(user_id)


async def resolve_duel_labels(
    bot: Any,
    group_id: int,
    challenger_id: str,
    defender_id: str,
) -> DuelLabels:
    ch_name, def_name = await asyncio.gather(
        fetch_group_member_display_name(bot, group_id, challenger_id),
        fetch_group_member_display_name(bot, group_id, defender_id),
    )
    return DuelLabels(
        challenger_id=str(challenger_id),
        defender_id=str(defender_id),
        challenger_name=ch_name,
        defender_name=def_name,
    )
