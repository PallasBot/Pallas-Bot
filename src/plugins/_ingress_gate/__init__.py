"""优先加载：Notice 门控 → 群消息分片 → 慢路径（仅通过分片的非优先群消息）。"""

from nonebot import get_driver, logger
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    NoticeEvent,
    PrivateMessageEvent,
)
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor, run_postprocessor
from nonebot.plugin import PluginMetadata

from src.common.ingress import (
    acquire_slow_event_slot,
    classify_notice,
    ingress_fast_lane_enabled,
    ingress_group_message_fanout_all_bots,
    ingress_multi_bot_shard_enabled,
    ingress_notice_gate_enabled,
    install_ingress_event_dispatch,
    release_slow_event_slot,
    should_apply_ingress_slow_path,
    should_sample_keep_notice,
    should_this_bot_handle_group_message,
    should_this_bot_handle_notice,
    start_ingress_slow_dispatch_workers,
    stop_ingress_slow_dispatch_workers,
)

__plugin_meta__ = PluginMetadata(
    name="入站分片",
    description="fast lane、Notice 采样/分片、多牛牛号群消息抢占。",
    usage="内部预处理器，无需用户命令。",
    type="application",
    extra={"menu_hidden": True},
)


def _onebot_v11_event(event: Event) -> bool:
    return "onebot.v11" in type(event).__module__


@event_preprocessor
async def ingress_notice_sample_and_shard(bot: Bot, event: NoticeEvent):
    if not _onebot_v11_event(event):
        return
    if not ingress_notice_gate_enabled():
        return
    ntype, sub = classify_notice(event)
    if not should_sample_keep_notice(ntype, sub):
        logger.debug("ingress_gate: notice sampled out type={} sub={}", ntype, sub)
        raise IgnoredException("ingress notice sample drop")
    if not await should_this_bot_handle_notice(int(bot.self_id), event):
        logger.debug("ingress_gate: notice shard drop bot={} type={}", bot.self_id, ntype)
        raise IgnoredException("ingress notice shard")


@event_preprocessor
async def shard_multi_bot_group_messages(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    if not _onebot_v11_event(event):
        return
    if isinstance(event, PrivateMessageEvent):
        return
    if not isinstance(event, GroupMessageEvent):
        return
    if not ingress_multi_bot_shard_enabled():
        return
    if int(event.self_id) == int(getattr(event, "user_id", 0) or 0):
        return
    if ingress_group_message_fanout_all_bots(event):
        return
    if not await should_this_bot_handle_group_message(int(bot.self_id), event):
        logger.debug(
            "ingress_gate: drop duplicate group event bot={} group={} key_len={}",
            bot.self_id,
            event.group_id,
            len(event.get_plaintext()),
        )
        raise IgnoredException("ingress multi-bot shard")


@event_preprocessor
async def ingress_slow_path_throttle(bot: Bot, event: Event):
    """分片之后：仅对通过分片的非优先群消息占慢路径槽（Meta/心跳/fast lane/全员同响跳过）。"""
    if not _onebot_v11_event(event):
        return
    if not should_apply_ingress_slow_path(event):
        return
    if not await acquire_slow_event_slot(event):
        logger.debug("ingress_gate: drop slow event (saturated) type={}", type(event).__name__)
        raise IgnoredException("ingress slow path saturated")
    from src.common.ingress.fast_lane import slow_event_overflow_held, slow_event_slot_held

    if should_apply_ingress_slow_path(event) and slow_event_overflow_held(event):
        logger.debug(
            "ingress_gate: slow path overflow slot type={}",
            type(event).__name__,
        )
    elif should_apply_ingress_slow_path(event) and not slow_event_slot_held(event):
        logger.debug(
            "ingress_gate: slow path pass-through (unlimited) type={}",
            type(event).__name__,
        )


@run_postprocessor
async def ingress_slow_path_release(bot: Bot, event: Event):
    if not _onebot_v11_event(event):
        return
    release_slow_event_slot(event)


driver = get_driver()


@driver.on_startup
async def log_ingress_gate_startup():
    from src.common.ingress.config import get_ingress_config
    from src.common.ingress.dispatch import slow_dispatch_queue_capacity, slow_dispatch_worker_count

    install_ingress_event_dispatch()
    if ingress_fast_lane_enabled():
        start_ingress_slow_dispatch_workers()

    cfg = get_ingress_config()
    logger.info(
        "ingress_gate startup: multi_bot_shard={} fast_lane={} notice_gate={} "
        "slow_concurrency={} slow_overflow={} slow_drop_on_timeout={} "
        "slow_dispatch_workers={} (cfg={}) slow_dispatch_queue_max={}",
        ingress_multi_bot_shard_enabled(),
        ingress_fast_lane_enabled(),
        ingress_notice_gate_enabled(),
        cfg.ingress_slow_concurrency,
        cfg.ingress_slow_overflow_concurrency,
        cfg.ingress_slow_drop_on_timeout,
        slow_dispatch_worker_count() if ingress_fast_lane_enabled() else 0,
        cfg.ingress_slow_dispatch_workers,
        slow_dispatch_queue_capacity() if ingress_fast_lane_enabled() else 0,
    )


@driver.on_shutdown
async def shutdown_ingress_dispatch():
    await stop_ingress_slow_dispatch_workers()
