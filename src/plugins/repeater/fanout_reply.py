"""多牛同群：判定可接话时由舰队内各牛各自发送；context 只查一次。"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nonebot import get_bot, get_bots, logger
from nonebot.exception import ActionFailed

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent


from itertools import starmap

from src.foundation.config import BotConfig
from src.platform.bot_runtime.send_unavailable import BOT_SEND_UNAVAILABLE_ERRORS, log_bot_send_unavailable
from src.platform.multi_bot.dedup import try_claim_group_message_once
from src.platform.shard import context as shard_ctx

from .config import get_repeater_config
from .model import Chat, ChatData
from .responder import ReplyBundle, Responder

_FANOUT_PLUGIN = "repeater_fanout"
_FANOUT_BOT_IDS_CACHE_TTL = 2.0
_FANOUT_BOT_IDS_CACHE: dict[int, tuple[float, list[int]]] = {}


@dataclass(frozen=True, slots=True)
class FanoutGate:
    """resolve_fanout_gate 结果：lost 时 handler 勿查库接话；won 时由 fanout 发送。"""

    lost: bool = False

    won: bool = False

    bot_ids: tuple[int, ...] = ()


async def count_fanout_capable_bots(group_id: int) -> int:
    return len(await list_fanout_bot_ids(group_id))


async def list_ready_fanout_bot_ids(group_id: int) -> list[int]:
    bot_ids = await list_fanout_bot_ids(group_id)
    if not bot_ids:
        return []
    ready = await asyncio.gather(*(BotConfig(bid, group_id).is_cooldown("repeat") for bid in bot_ids))
    return [bid for bid, ok in zip(bot_ids, ready, strict=True) if ok]


async def repeater_can_attempt_reply(bot_id: int, group_id: int) -> bool:
    if not repeater_fanout_enabled():
        return await BotConfig(bot_id, group_id).is_cooldown("repeat")
    return bool(await list_ready_fanout_bot_ids(group_id))


def repeater_fanout_enabled() -> bool:
    if not get_repeater_config().fanout_enabled:
        return False
    if not shard_ctx.sharding_active():
        return len(get_bots()) > 1
    return True


async def repeater_fanout_enabled_for_group(group_id: int) -> bool:
    """与单进程一致：仅当群内不少于 2 只可复读的在线牛时才 fanout。"""
    if not repeater_fanout_enabled():
        return False
    if not shard_ctx.sharding_active():
        return len(get_bots()) > 1
    return await count_fanout_capable_bots(group_id) >= 2


def cap_fanout_bot_ids(bot_ids: list[int]) -> list[int]:

    limit = int(get_repeater_config().fanout_max_bots)

    if limit <= 0:
        return bot_ids

    return bot_ids[:limit]


def fanout_payload_from_event(event: GroupMessageEvent, bundle: ReplyBundle) -> dict[str, Any]:

    return {
        "group_id": int(event.group_id),
        "user_id": int(event.user_id),
        "raw_message": event.raw_message,
        "plain_text": (event.get_plaintext() or "").strip(),
        "time": int(event.time),
        "reply_bundle": {
            "answer_list": list(bundle.answer_list),
            "answer_keywords": bundle.answer_keywords,
            "message_pool": list(bundle.message_pool),
        },
    }


def bundle_from_payload(payload: dict[str, Any]) -> ReplyBundle | None:

    raw = payload.get("reply_bundle")

    if not isinstance(raw, dict):
        return None

    answer_list = raw.get("answer_list")

    if not isinstance(answer_list, list) or not answer_list:
        return None

    keywords = str(raw.get("answer_keywords") or "")

    pool = raw.get("message_pool")

    if not isinstance(pool, list) or not pool:
        pool = list(answer_list)

    return ReplyBundle(
        answer_list=[str(x) for x in answer_list],
        answer_keywords=keywords,
        message_pool=[str(x) for x in pool],
    )


async def bot_may_repeater_reply(bot_id: int, group_id: int) -> bool:

    cfg = BotConfig(bot_id, group_id)

    if await cfg.is_sleep():
        return False

    try:
        from src.plugins.help.plugin_manager import is_plugin_disabled

        if await is_plugin_disabled("repeater", group_id, bot_id):
            return False

    except Exception:
        pass

    return True


async def list_fanout_bot_ids(group_id: int) -> list[int]:
    cached = _FANOUT_BOT_IDS_CACHE.get(group_id)
    now = time.monotonic()
    if cached is not None and cached[0] > now:
        return list(cached[1])

    from src.platform.shard.presence import get_cluster_online_bot_ids
    from src.plugins.duel.duel_bots import list_group_online_bot_ids

    ids = await list_group_online_bot_ids(group_id)

    if not ids:
        return []

    if shard_ctx.sharding_active():
        online = get_cluster_online_bot_ids()
        ids = [bid for bid in ids if bid in online]

    if not ids:
        return []

    allowed = await asyncio.gather(*(bot_may_repeater_reply(bid, group_id) for bid in ids))

    result = cap_fanout_bot_ids([bid for bid, ok in zip(ids, allowed, strict=True) if ok])
    _FANOUT_BOT_IDS_CACHE[group_id] = (now + _FANOUT_BOT_IDS_CACHE_TTL, list(result))
    return result


async def resolve_fanout_gate(event: GroupMessageEvent) -> FanoutGate:
    """一次 list + claim；失败者 lost=True，成功者 won=True 并带上 bot_ids。"""

    group_id = int(event.group_id)
    if not repeater_fanout_enabled():
        return FanoutGate()

    bot_ids = await list_fanout_bot_ids(group_id)

    if len(bot_ids) < 2:
        return FanoutGate()

    if not await try_claim_group_message_once(
        _FANOUT_PLUGIN,
        event.group_id,
        event.user_id,
        event.get_plaintext(),
        event.time,
    ):
        return FanoutGate(lost=True)

    return FanoutGate(won=True, bot_ids=tuple(bot_ids))


async def _run_repeater_reply_send(bot_id: int, group_id: int, answers) -> None:
    try:
        await send_repeater_answers(bot_id, group_id, answers)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("repeater reply background failed bot={} group={}: {}", bot_id, group_id, e)


def dispatch_repeater_reply(bot_id: int, group_id: int, answers) -> None:
    """单牛接话：sleep + 多段 send 放到后台，避免占用 on_message matcher 墙钟。"""
    asyncio.create_task(
        _run_repeater_reply_send(int(bot_id), int(group_id), answers),
        name=f"repeater_reply_{bot_id}_{group_id}",
    )


async def send_repeater_answers(bot_id: int, group_id: int, answers) -> None:

    from src.plugins.repeater import post_proc

    from .model import Chat

    config = BotConfig(bot_id, group_id)

    await config.refresh_cooldown("repeat")

    delay = random.randint(2, 5)

    try:
        bot = get_bot(str(bot_id))

    except ValueError:
        logger.warning("repeater_fanout: bot [{}] not connected on this worker", bot_id)

        return

    async for item in answers:
        msg = await post_proc(item, bot_id, group_id)

        logger.info(f"bot [{bot_id}] ready to send [{str(msg)[:30]}] to group [{group_id}] (fanout)")

        await asyncio.sleep(delay)

        await config.refresh_cooldown("repeat")

        try:
            await bot.send_group_msg(group_id=group_id, message=msg)

        except BOT_SEND_UNAVAILABLE_ERRORS as e:
            log_bot_send_unavailable(e, context="repeater_fanout", bot=bot_id, group=group_id)

            return

        except ActionFailed:
            if not await BotConfig(bot_id).security():
                continue

            from src.plugins.repeater import is_shutup

            shutup = await is_shutup(bot_id, group_id)

            if not shutup:
                logger.info(f"bot [{bot_id}] ready to ban [{str(item)}] in group [{group_id}] (fanout)")

                await Chat.ban(group_id, bot_id, str(item), "ActionFailed")

                break

        delay = random.randint(1, 3)


async def run_repeater_reply_for_bot(bot_id: int, payload: dict[str, Any]) -> None:

    group_id = int(payload["group_id"])

    if not await bot_may_repeater_reply(bot_id, group_id):
        return

    config = BotConfig(bot_id, group_id)

    if not await config.is_cooldown("repeat"):
        return

    bundle = bundle_from_payload(payload)

    if bundle is None:
        return

    chat_data = ChatData(
        group_id=group_id,
        user_id=int(payload["user_id"]),
        raw_message=str(payload["raw_message"]),
        plain_text=str(payload["plain_text"]),
        time=int(payload["time"]),
        bot_id=bot_id,
    )

    plan = Responder.pick_fanout_plan(bundle)

    chat = Chat(chat_data)

    answers = await chat.answer_from_bundle(bundle, plan=plan)

    if answers is None:
        return

    await send_repeater_answers(bot_id, group_id, answers)


async def dispatch_repeater_fanout(
    event: GroupMessageEvent,
    bot_ids: list[int] | tuple[int, ...],
    bundle: ReplyBundle,
) -> None:
    payload = fanout_payload_from_event(event, bundle)
    group_id = int(event.group_id)
    ids = list(bot_ids)
    stagger = 0.35

    from src.platform.shard.presence import bot_has_cluster_connection, bot_has_local_connection

    local: list[tuple[int, int]] = []
    remote: list[tuple[int, int]] = []
    for i, bid in enumerate(ids):
        if not bot_has_cluster_connection(bid):
            logger.debug(f"repeater_fanout skip offline bot={bid} group={group_id}")
            continue
        delay = i * stagger
        if bot_has_local_connection(bid):
            local.append((bid, delay))
        elif shard_ctx.sharding_active():
            remote.append((bid, delay))

    for bid, delay in local:
        asyncio.create_task(
            _delayed_local_reply(delay, bid, payload),
            name=f"repeater_fanout_{bid}_{group_id}",
        )

    if remote:
        asyncio.create_task(
            _dispatch_remote_fanout_batch(remote, payload, group_id),
            name=f"repeater_fanout_remote_batch_{group_id}",
        )


async def _dispatch_remote_fanout_batch(
    remote: list[tuple[int, int]],
    payload: dict[str, Any],
    group_id: int,
) -> None:
    from src.platform.shard.coord.bot_action import invoke_bot_action

    async def one(bid: int, delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            await invoke_bot_action(
                "repeater_fanout_reply",
                int(bid),
                payload,
                timeout_sec=45.0,
            )
        except Exception as e:
            logger.warning("repeater_fanout remote bot={} failed: {}", bid, e)

    await asyncio.gather(*starmap(one, remote))


async def _delayed_local_reply(delay: float, bot_id: int, payload: dict[str, Any]) -> None:

    if delay > 0:
        await asyncio.sleep(delay)

    try:
        await run_repeater_reply_for_bot(bot_id, payload)

    except Exception as e:
        logger.warning("repeater_fanout local bot={} failed: {}", bot_id, e)
