"""本进程已连接牛牛 QQ 集合。"""

from __future__ import annotations

import asyncio

from nonebot import get_driver, logger
from nonebot.adapters import Bot  # noqa: TC002

from pallas.core.foundation.db import ensure_bot_config_row, ensure_runtime_storage_ready
from pallas.core.platform.multi_bot.session_seen import note_bot_session_seen
from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.presence import (
    clear_protocol_bot_offline,
    note_worker_bot_connected,
    note_worker_bot_disconnected,
)
from pallas.core.platform.shard.presence_health import clear_health_quarantine

_connected_bots: set[int] = set()
_hooks_registered = False


async def ensure_bot_runtime_storage(qq: int) -> bool:
    _ = qq
    return await ensure_runtime_storage_ready()


def connected_bot_ids() -> set[int]:
    return _connected_bots


def note_connected_bot(qq: int) -> None:
    _connected_bots.add(int(qq))


def note_disconnected_bot(qq: int) -> None:
    _connected_bots.discard(int(qq))


async def on_bot_connect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "OneBot V11":
        logger.info(f"Bot {bot.self_id} connected.")
        qq = int(bot.self_id)
        note_connected_bot(qq)
        note_bot_session_seen(qq)
        await clear_protocol_bot_offline(qq)
        clear_health_quarantine(qq)
        try:
            initialized = await ensure_bot_runtime_storage(qq)
            if initialized:
                logger.info("Bot {} runtime storage initialized on connect.", bot.self_id)
            else:
                logger.info("Bot {} runtime storage already ready on connect.", bot.self_id)
        except Exception as err:
            logger.warning("Bot {} runtime storage ensure failed: {}", bot.self_id, err)
        try:
            created = await ensure_bot_config_row(qq)
            if created:
                logger.info("bot_config ensured for Bot {}", bot.self_id)
            else:
                logger.debug("bot_config already exists for Bot {}", bot.self_id)
        except Exception as err:
            logger.warning("Bot {} bot_config ensure failed: {}", bot.self_id, err)
        if shard_ctx.sharding_active():
            await note_worker_bot_connected(bot)
        try:
            from pallas.core.platform.federate.peer_bots import sync_federate_peer_bot_roster

            asyncio.create_task(sync_federate_peer_bot_roster(), name=f"federate_peer_sync_connect:{qq}")
        except Exception:
            pass


async def on_bot_disconnect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "OneBot V11":
        qq = int(bot.self_id)
        was_present = qq in _connected_bots
        note_disconnected_bot(qq)
        if was_present:
            logger.info(f"Bot {bot.self_id} disconnected.")
        await clear_protocol_bot_offline(qq)
        if shard_ctx.sharding_active():
            await note_worker_bot_disconnected(qq)
        try:
            from pallas.core.platform.federate.peer_bots import sync_federate_peer_bot_roster

            asyncio.create_task(
                sync_federate_peer_bot_roster(),
                name=f"federate_peer_sync_disconnect:{int(bot.self_id)}",
            )
        except Exception:
            pass


def register_connected_roster_hooks() -> None:
    global _hooks_registered
    if _hooks_registered:
        return
    driver = get_driver()
    driver.on_bot_connect(on_bot_connect)
    driver.on_bot_disconnect(on_bot_disconnect)
    _hooks_registered = True
