"""定时主动发言与数据维护。"""

from __future__ import annotations

import asyncio
import random

from nonebot import get_bot, get_driver, logger
from nonebot.exception import ActionFailed
from nonebot_plugin_apscheduler import scheduler

from pallas.api.logging import format_plugin_event
from pallas.core.foundation.db.lifecycle_service import run_lifecycle_dataset_maintenance
from pallas.core.foundation.logging.bridge import format_business_event
from pallas.core.platform.ingress.message_load import should_pause_tasks
from pallas.core.platform.shard import context as shard_ctx

from ..message_store import MessageStore
from ..model import Chat
from ..runtime_stats import prune_repeater_runtime_caches
from ..shard_opt import repeater_maintenance_runs_on_worker, repeater_scheduler_runs_on_worker

driver = get_driver()


async def run_image_cache_prune() -> None:
    if not repeater_maintenance_runs_on_worker():
        return
    try:
        await run_lifecycle_dataset_maintenance("image_cache")
    except Exception:
        logger.exception("image cache prune failed")


@driver.on_startup
async def schedule_image_cache_prune_after_startup() -> None:
    asyncio.create_task(run_image_cache_prune(), name="image_cache_prune_startup")


@scheduler.scheduled_job("cron", hour=4, minute=30)
async def prune_image_cache_daily() -> None:
    await run_image_cache_prune()


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
        logger.debug(format_business_event("主动发言", "已准备", bot=bot_id, group=group_id, content_len=len(str(msg))))
        try:
            from pallas.product.llm.sticker_followup import suppress_outgoing_sticker_followup

            with suppress_outgoing_sticker_followup():
                await bot.call_api(
                    "send_group_msg",
                    **{
                        "message": msg,
                        "group_id": group_id,
                    },
                )

            from ..sticker_followup import maybe_send_repeater_sticker_followup

            await maybe_send_repeater_sticker_followup(bot, group_id, str(msg))
            if target_id:
                await bot.call_api(
                    "group_poke",
                    **{
                        "user_id": target_id,
                        "group_id": group_id,
                    },
                )
            suffix = f" and poked user [{target_id}]" if target_id else ""
            logger.info(
                format_plugin_event(
                    "speak_up",
                    f"Bot [{bot_id}] spoke up in group [{group_id}]: {msg}{suffix}",
                )
            )
        except ActionFailed as e:
            logger.warning(
                format_business_event("主动发言", "发送失败", bot=bot_id, group=group_id, error=type(e).__name__)
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
        logger.info(
            "Runtime cache pruned: message groups [{}], message records [{}], "
            "reply groups [{}], reply bot buckets [{}], reply records [{}], recent topic groups [{}]",
            removed["message_groups_removed"],
            removed["message_records_removed"],
            removed["reply_groups_removed"],
            removed["reply_bot_buckets_removed"],
            removed["reply_records_removed"],
            removed["recent_topics_groups_removed"],
        )


@scheduler.scheduled_job("interval", minutes=10)
async def sync_message_store_periodically() -> None:
    if shard_ctx.sharding_active() and shard_ctx.is_hub():
        return
    await MessageStore.periodic_sync_if_buffered()
