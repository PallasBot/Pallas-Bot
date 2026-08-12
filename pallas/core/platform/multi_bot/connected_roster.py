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
_shutting_down = False


async def ensure_bot_runtime_storage(qq: int) -> bool:
    _ = qq
    return await ensure_runtime_storage_ready()


def connected_bot_ids() -> set[int]:
    return _connected_bots


def note_connected_bot(qq: int) -> None:
    _connected_bots.add(int(qq))


def note_disconnected_bot(qq: int) -> None:
    _connected_bots.discard(int(qq))


def mark_process_shutting_down() -> None:
    """置位进程正在收尾；断连等事件处理应转为静默。"""
    global _shutting_down
    _shutting_down = True


def is_process_shutting_down() -> bool:
    return _shutting_down


async def on_bot_connect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "OneBot V11":
        logger.debug("[Bot {:>10}] connected.", bot.self_id)
        qq = int(bot.self_id)
        from pallas.core.platform.shard.presence import close_local_bot_connection
        from pallas.core.platform.shard.presence_health import (
            health_quarantine_qq_ids,
            probe_bot_get_status_healthy,
        )

        # 隔离中的重连：先探测会话；仍不健康则关 WS，避免清 quarantine 后假在线。
        if qq in health_quarantine_qq_ids():
            if not await probe_bot_get_status_healthy(bot):
                logger.warning(
                    "[Bot {:>10}] reconnected while quarantined but get_status unhealthy; closing WS",
                    bot.self_id,
                )
                await close_local_bot_connection(qq)
                return
            clear_health_quarantine(qq)

        note_connected_bot(qq)
        note_bot_session_seen(qq)
        await clear_protocol_bot_offline(qq)
        clear_health_quarantine(qq)
        try:
            initialized = await ensure_bot_runtime_storage(qq)
            if initialized:
                logger.info("[Bot {:>10}] runtime storage initialized on connect.", bot.self_id)
            else:
                logger.debug("[Bot {:>10}] runtime storage already ready on connect.", bot.self_id)
        except Exception as err:
            logger.warning("[Bot {:>10}] runtime storage ensure failed: {}", bot.self_id, err)
        try:
            created = await ensure_bot_config_row(qq)
            if created:
                logger.info("[Bot {:>10}] runtime config initialized.", bot.self_id)
            else:
                logger.debug("[Bot {:>10}] runtime config already ready.", bot.self_id)
        except Exception as err:
            logger.warning("[Bot {:>10}] runtime config ensure failed: {}", bot.self_id, err)
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
            if _shutting_down:
                logger.debug("[Bot {:>10}] disconnected.", bot.self_id)
            else:
                logger.info("[Bot {:>10}] disconnected.", bot.self_id)
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
