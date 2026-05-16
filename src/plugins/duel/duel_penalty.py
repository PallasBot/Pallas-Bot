from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from nonebot import get_bots, logger, on_message
from nonebot.adapters import Bot  # noqa: TC002
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.exception import ActionFailed
from nonebot.rule import Rule

from src.common.config import BotConfig, GroupConfig
from src.common.utils import is_bot_admin
from src.plugins.duel.config import plugin_config
from src.plugins.duel.duel_bots import is_bot_qq

if TYPE_CHECKING:
    from src.plugins.duel.duel_round_engine import DuelStacks

_PENALTIES_KEY = "duel_penalties"


class PenaltyKind(StrEnum):
    BOT_FAKE = "bot_fake"
    BOT_SAD = "bot_sad"
    HUMAN_NOISE = "human_noise"
    CARD_ONLY = "card_only"


@dataclass
class ActivePenalty:
    group_id: int
    user_id: int
    kind: PenaltyKind
    handler_bot_id: int
    applied_bot_id: int
    original_card: str
    expires_at: float


_restore_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}


def resolve_winner_loser(challenger_id: str, defender_id: str, stacks: DuelStacks) -> tuple[str, str] | None:
    """与终幕胜负一致；平局返回 None。"""
    chp, dhp = stacks.challenger_hp, stacks.defender_hp
    if chp <= 0 and dhp <= 0:
        return None
    if chp <= 0:
        return defender_id, challenger_id
    if dhp <= 0:
        return challenger_id, defender_id
    if chp > dhp:
        return challenger_id, defender_id
    if dhp > chp:
        return defender_id, challenger_id
    return None


def _penalty_to_dict(pen: ActivePenalty) -> dict[str, Any]:
    return {
        "kind": str(pen.kind),
        "handler_bot_id": pen.handler_bot_id,
        "applied_bot_id": pen.applied_bot_id,
        "original_card": pen.original_card,
        "expires_at": pen.expires_at,
    }


def _penalty_from_dict(group_id: int, user_id: int, raw: dict[str, Any]) -> ActivePenalty | None:
    try:
        kind = PenaltyKind(str(raw["kind"]))
        return ActivePenalty(
            group_id=group_id,
            user_id=user_id,
            kind=kind,
            handler_bot_id=int(raw["handler_bot_id"]),
            applied_bot_id=int(raw["applied_bot_id"]),
            original_card=str(raw.get("original_card") or ""),
            expires_at=float(raw["expires_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def _read_penalties_map(group_id: int) -> dict[str, dict[str, Any]]:
    gc = GroupConfig(group_id)
    raw = await gc._find_in_memory(_PENALTIES_KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[str(k)] = v
    return out


async def _write_penalties_map(group_id: int, data: dict[str, dict[str, Any]]) -> None:
    gc = GroupConfig(group_id)
    await gc._update_in_memory(_PENALTIES_KEY, data)


async def _load_penalty(group_id: int, user_id: int) -> ActivePenalty | None:
    data = await _read_penalties_map(group_id)
    raw = data.get(str(user_id))
    if not raw:
        return None
    return _penalty_from_dict(group_id, user_id, raw)


async def _save_penalty(pen: ActivePenalty) -> None:
    data = await _read_penalties_map(pen.group_id)
    data[str(pen.user_id)] = _penalty_to_dict(pen)
    await _write_penalties_map(pen.group_id, data)


async def _delete_penalty(group_id: int, user_id: int) -> ActivePenalty | None:
    data = await _read_penalties_map(group_id)
    raw = data.pop(str(user_id), None)
    await _write_penalties_map(group_id, data)
    if not raw:
        return None
    return _penalty_from_dict(group_id, user_id, raw)


async def get_active_penalty_async(group_id: int, user_id: int) -> ActivePenalty | None:
    pen = await _load_penalty(group_id, user_id)
    if pen is None:
        return None
    if time.time() >= pen.expires_at:
        await _restore_one(group_id, user_id)
        return None
    return pen


async def fetch_member_card(bot_id: int, group_id: int, user_id: int) -> str:
    bot = get_bots().get(str(bot_id))
    if bot is None:
        return ""
    try:
        info = await bot.call_api(
            "get_group_member_info",
            **{"group_id": group_id, "user_id": int(user_id), "no_cache": True},
        )
    except ActionFailed:
        return ""
    return str(info.get("card") or info.get("nickname") or "").strip()


async def set_member_card(bot_id: int, group_id: int, user_id: int, card: str) -> bool:
    bot = get_bots().get(str(bot_id))
    if bot is None:
        return False
    try:
        await bot.call_api(
            "set_group_card",
            **{"group_id": group_id, "user_id": int(user_id), "card": card[:60]},
        )
        return True
    except ActionFailed as err:
        logger.debug(f"duel penalty set_group_card failed gid={group_id} uid={user_id}: {err}")
        return False


def _penalty_duration_sec() -> float:
    return float(plugin_config.duel_penalty_minutes * 60)


async def _restore_one(group_id: int, user_id: int) -> None:
    key = (group_id, user_id)
    _restore_tasks.pop(key, None)
    pen = await _delete_penalty(group_id, user_id)
    if pen is None:
        return
    await set_member_card(pen.applied_bot_id, group_id, user_id, pen.original_card)
    logger.info(f"duel penalty restored card gid={group_id} uid={user_id}")


def _schedule_restore(group_id: int, user_id: int, delay_sec: float) -> None:
    key = (group_id, user_id)

    async def job() -> None:
        try:
            await asyncio.sleep(delay_sec)
            await _restore_one(group_id, user_id)
        except asyncio.CancelledError:
            return

    old = _restore_tasks.pop(key, None)
    if old is not None:
        old.cancel()
    _restore_tasks[key] = asyncio.create_task(job())


async def register_penalty(
    group_id: int,
    user_id: str | int,
    *,
    kind: PenaltyKind,
    handler_bot_id: int,
    applied_bot_id: int,
    display_card: str | None,
) -> None:
    uid = int(user_id)
    duration = _penalty_duration_sec()
    original = await fetch_member_card(applied_bot_id, group_id, uid)
    if display_card:
        await set_member_card(applied_bot_id, group_id, uid, display_card)
    pen = ActivePenalty(
        group_id=group_id,
        user_id=uid,
        kind=kind,
        handler_bot_id=handler_bot_id,
        applied_bot_id=applied_bot_id,
        original_card=original,
        expires_at=time.time() + duration,
    )
    await _save_penalty(pen)
    _schedule_restore(group_id, uid, duration)
    logger.info(
        f"duel penalty start gid={group_id} uid={uid} kind={kind} "
        f"handler={handler_bot_id} min={plugin_config.duel_penalty_minutes}"
    )


async def apply_dual_bot_penalties(
    group_id: int,
    handler_bot_id: int,
    winner_id: str,
    loser_id: str,
) -> None:
    await register_penalty(
        group_id,
        loser_id,
        kind=PenaltyKind.BOT_FAKE,
        handler_bot_id=handler_bot_id,
        applied_bot_id=int(loser_id),
        display_card=plugin_config.duel_penalty_loser_card,
    )
    await register_penalty(
        group_id,
        winner_id,
        kind=PenaltyKind.CARD_ONLY,
        handler_bot_id=handler_bot_id,
        applied_bot_id=int(winner_id),
        display_card=plugin_config.duel_penalty_winner_card,
    )


async def apply_duel_penalties(
    group_id: int,
    handler_bot_id: int,
    challenger_id: str,
    defender_id: str,
    stacks: DuelStacks,
    *,
    dual_bot: bool,
) -> None:
    pair = resolve_winner_loser(challenger_id, defender_id, stacks)
    if not pair:
        return
    winner_id, loser_id = pair

    if dual_bot:
        await apply_dual_bot_penalties(group_id, handler_bot_id, winner_id, loser_id)
        return

    if not await is_bot_admin(handler_bot_id, group_id):
        return

    if is_bot_qq(loser_id):
        await register_penalty(
            group_id,
            loser_id,
            kind=PenaltyKind.BOT_SAD,
            handler_bot_id=handler_bot_id,
            applied_bot_id=int(loser_id),
            display_card=plugin_config.duel_penalty_loser_card,
        )
        return

    await register_penalty(
        group_id,
        loser_id,
        kind=PenaltyKind.HUMAN_NOISE,
        handler_bot_id=handler_bot_id,
        applied_bot_id=handler_bot_id,
        display_card=plugin_config.duel_penalty_loser_card,
    )


async def is_duel_penalty_message(bot: Bot, event: GroupMessageEvent) -> bool:
    if await BotConfig(event.self_id, event.group_id).is_sleep():
        return False
    pen = await get_active_penalty_async(event.group_id, int(event.user_id))
    if pen is None:
        return False
    if pen.kind not in (PenaltyKind.BOT_FAKE, PenaltyKind.BOT_SAD, PenaltyKind.HUMAN_NOISE):
        return False
    return int(event.self_id) == pen.handler_bot_id


duel_penalty_msg = on_message(
    priority=2,
    block=True,
    rule=Rule(is_duel_penalty_message),
    permission=permission.GROUP,
)


@duel_penalty_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent) -> None:
    pen = await get_active_penalty_async(event.group_id, int(event.user_id))
    if pen is None:
        return
    try:
        await bot.delete_msg(message_id=event.message_id)
    except ActionFailed as err:
        logger.debug(f"duel penalty delete_msg failed gid={event.group_id}: {err}")

    if pen.kind == PenaltyKind.HUMAN_NOISE:
        try:
            await bot.send_group_msg(
                group_id=event.group_id,
                message=plugin_config.duel_penalty_human_noise_msg,
            )
        except ActionFailed as err:
            logger.debug(f"duel penalty noise send failed gid={event.group_id}: {err}")
        return

    reply = (
        plugin_config.duel_penalty_bot_fake_msg
        if pen.kind == PenaltyKind.BOT_FAKE
        else plugin_config.duel_penalty_bot_sad_msg
    )
    inst = get_bots().get(str(event.user_id))
    if inst is None:
        return
    try:
        await inst.send_group_msg(group_id=event.group_id, message=reply)
    except ActionFailed as err:
        logger.debug(f"duel penalty bot reply failed gid={event.group_id} uid={event.user_id}: {err}")
