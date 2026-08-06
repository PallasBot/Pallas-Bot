from __future__ import annotations

import asyncio

from nonebot import get_driver, logger

from pallas.core.foundation.db.pool_budget import pool_budget_status
from pallas.core.foundation.startup_report import register_startup_fact
from pallas.core.platform.bot_runtime.roles import is_hub_role
from pallas.core.platform.ingress.adaptive_capacity import adaptive_chat_lane_target, adaptive_scheduler_target
from pallas.core.platform.ingress.conversation_scheduler import (
    conversation_scheduler_status,
    set_conversation_scheduler_concurrency,
    start_conversation_scheduler,
    stop_conversation_scheduler,
)
from pallas.core.platform.ingress.dispatch_lanes import DispatchLane, lane_status, set_lane_limit
from pallas.core.platform.ingress.dispatch_runtime_config import get_ingress_dispatch_runtime_config
from pallas.core.platform.ingress.dispatch_stats_logger import (
    start_dispatch_stats_logger,
    stop_dispatch_stats_logger,
)
from pallas.core.platform.ingress.matcher_dispatch import (
    install_matcher_dispatch,
    matcher_dispatch_enabled,
    uninstall_matcher_dispatch,
)
from pallas.core.platform.ingress.onebot_backpressure import install_onebot_backpressure, uninstall_onebot_backpressure
from pallas.core.platform.ingress.route_index import build_route_index, route_index_enabled, route_index_strict
from pallas.core.platform.ingress.send_queue import (
    install_send_queue,
    send_queue_status,
    start_send_queue_workers,
    stop_send_queue_workers,
    uninstall_send_queue,
)

_HOOK_REGISTERED = False
_ADAPTIVE_CAPACITY_TASK: asyncio.Task[None] | None = None
_ADAPTIVE_CHAT_LANE_BASELINE: int | None = None


async def adaptive_capacity_loop() -> None:
    while True:
        config = get_ingress_dispatch_runtime_config()
        scheduler = conversation_scheduler_status()
        pool = pool_budget_status()
        send_queue = send_queue_status()
        current = int(scheduler.get("concurrency") or config.conversation_scheduler_concurrency)
        target = adaptive_scheduler_target(
            current=current,
            baseline=config.conversation_scheduler_concurrency,
            maximum=config.conversation_scheduler_adaptive_max,
            scheduler=scheduler,
            pool=pool,
            send_queue=send_queue,
        )
        if target != current:
            await set_conversation_scheduler_concurrency(target)
        lanes = lane_status()
        chat_lane = lanes.get(str(DispatchLane.CHAT))
        if chat_lane is not None:
            chat_current = int(chat_lane.get("limit") or 1)
            chat_baseline = _ADAPTIVE_CHAT_LANE_BASELINE or chat_current
            chat_target = adaptive_chat_lane_target(
                current=chat_current,
                baseline=chat_baseline,
                maximum=config.lane_chat_adaptive_max,
                scheduler=scheduler,
                chat_lane=chat_lane,
                pool=pool,
                send_queue=send_queue,
            )
            if chat_target != chat_current:
                await set_lane_limit(DispatchLane.CHAT, chat_target)
        await asyncio.sleep(config.conversation_scheduler_adaptive_interval_sec)


def start_adaptive_capacity_loop() -> None:
    global _ADAPTIVE_CAPACITY_TASK, _ADAPTIVE_CHAT_LANE_BASELINE
    if _ADAPTIVE_CAPACITY_TASK is None:
        chat_lane = lane_status().get(str(DispatchLane.CHAT))
        _ADAPTIVE_CHAT_LANE_BASELINE = int(chat_lane.get("limit") or 1) if chat_lane is not None else None
        _ADAPTIVE_CAPACITY_TASK = asyncio.create_task(adaptive_capacity_loop(), name="ingress_adaptive_capacity")


async def stop_adaptive_capacity_loop() -> None:
    global _ADAPTIVE_CAPACITY_TASK, _ADAPTIVE_CHAT_LANE_BASELINE
    task = _ADAPTIVE_CAPACITY_TASK
    _ADAPTIVE_CAPACITY_TASK = None
    _ADAPTIVE_CHAT_LANE_BASELINE = None
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def register_ingress_dispatch_runtime() -> None:
    global _HOOK_REGISTERED
    if _HOOK_REGISTERED or is_hub_role():
        return
    try:
        driver = get_driver()
    except ValueError:
        return

    @driver.on_startup
    async def install_ingress_dispatch_on_startup() -> None:
        if route_index_enabled():
            index = build_route_index()
            register_startup_fact(
                "ingress",
                f"prefix={len(index.prefix_to_modules)} "
                f"exact={len(index.exact_to_modules)} "
                f"modules={len(index.indexed_modules)} "
                f"strict={route_index_strict()}",
            )
        install_send_queue()
        await start_send_queue_workers()
        await start_conversation_scheduler()
        start_adaptive_capacity_loop()
        install_onebot_backpressure()
        install_matcher_dispatch()
        start_dispatch_stats_logger()

    @driver.on_shutdown
    async def uninstall_ingress_dispatch_on_shutdown() -> None:
        await stop_dispatch_stats_logger()
        await stop_adaptive_capacity_loop()
        await stop_conversation_scheduler()
        uninstall_matcher_dispatch()
        uninstall_onebot_backpressure()
        await stop_send_queue_workers()
        uninstall_send_queue()

    _HOOK_REGISTERED = True
    if matcher_dispatch_enabled():
        logger.debug("bot_runtime: ingress dispatch runtime registered")


def ingress_dispatch_runtime_registered() -> bool:
    return _HOOK_REGISTERED
