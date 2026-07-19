"""定时主动发言与数据维护。"""

from __future__ import annotations

import asyncio
import random

from nonebot import get_bot, logger
from nonebot.exception import ActionFailed
from nonebot_plugin_apscheduler import scheduler

from pallas.core.platform.ingress.message_load import should_pause_tasks
from pallas.core.platform.shard import context as shard_ctx

from ..message_store import MessageStore
from ..model import Chat
from ..runtime_stats import prune_repeater_runtime_caches
from ..shard_opt import repeater_maintenance_runs_on_worker, repeater_scheduler_runs_on_worker


@scheduler.scheduled_job("interval", seconds=60)
async def speak_up():
    if should_pause_tasks():
        return
    if not repeater_scheduler_runs_on_worker():
        return
    ret = await Chat.speak()
    if not ret:
        return

    bot_id, group_id, messages, target_id = ret

    try:
        bot = get_bot(str(bot_id))
    except (KeyError, ValueError):
        logger.debug("speak_up skip bot [{}] not connected on this worker", bot_id)
        return

    for msg in messages:
        logger.info(f"bot [{bot_id}] ready to speak [{msg}] to group [{group_id}]")
        try:
            await bot.call_api(
                "send_group_msg",
                **{
                    "message": msg,
                    "group_id": group_id,
                },
            )
            if target_id:
                await bot.call_api(
                    "group_poke",
                    **{
                        "user_id": target_id,
                        "group_id": group_id,
                    },
                )
        except ActionFailed as e:
            logger.warning(
                "bot [{}] speak_up send failed group [{}]: {}",
                bot_id,
                group_id,
                e,
            )
            return
        await asyncio.sleep(random.randint(2, 5))


@scheduler.scheduled_job("cron", hour=4)
async def update_data():
    if not repeater_maintenance_runs_on_worker():
        return
    await Chat.sync()
    await Chat.clearup_context()


@scheduler.scheduled_job("interval", minutes=10)
async def prune_runtime_caches() -> None:
    if shard_ctx.sharding_active() and shard_ctx.is_hub():
        return
    removed = await prune_repeater_runtime_caches()
    if any(int(value) > 0 for value in removed.values()):
        logger.info("repeater.runtime_cache_pruned {}", removed)


@scheduler.scheduled_job("interval", minutes=10)
async def sync_message_store_periodically() -> None:
    if shard_ctx.sharding_active() and shard_ctx.is_hub():
        return
    await MessageStore.periodic_sync_if_buffered()
