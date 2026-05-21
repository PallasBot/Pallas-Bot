"""入站调度：fast lane 异步 handle_event，水群有界队列 + worker，入口分片。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nonebot import logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.common.ingress.config import clear_ingress_config_cache, get_ingress_config
from src.common.ingress.fast_lane import (
    acquire_slow_event_slot,
    clear_ingress_slow_path_runtime_state,
    ingress_fast_lane_enabled,
    release_slow_event_slot,
    should_apply_ingress_slow_path,
)
from src.common.ingress.gate import should_skip_ingress_dispatch_for_bot

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters import Bot, Event

if TYPE_CHECKING:
    HandleEventFn = Callable[[Bot, Event], Awaitable[None]]

_orig_handle_event: HandleEventFn | None = None
_slow_queue: asyncio.Queue[tuple[Bot, Event, float] | None] | None = None
_slow_worker_tasks: list[asyncio.Task[None]] = []
_dispatch_installed = False
_SLOW_QUEUE_WAIT_LOG_MS = 200.0


def slow_dispatch_queue_capacity() -> int:
    cfg = get_ingress_config()
    return max(128, (cfg.ingress_slow_concurrency + cfg.ingress_slow_overflow_concurrency) * 8)


def slow_dispatch_worker_count() -> int:
    cfg = get_ingress_config()
    if cfg.ingress_slow_dispatch_workers > 0:
        return max(1, cfg.ingress_slow_dispatch_workers)
    return max(1, min(cfg.ingress_slow_concurrency, 24))


def _slow_queue_capacity() -> int:
    return slow_dispatch_queue_capacity()


def _slow_worker_count() -> int:
    return slow_dispatch_worker_count()


async def _run_handle_event(bot: Bot, event: Event) -> None:
    assert _orig_handle_event is not None
    try:
        await _orig_handle_event(bot, event)
    except Exception:
        logger.exception(
            "ingress_dispatch: handle_event failed bot={} type={}",
            bot.self_id,
            type(event).__name__,
        )


def _schedule_handle_event(bot: Bot, event: Event) -> None:
    asyncio.create_task(
        _run_handle_event(bot, event),
        name=f"ingress-{bot.self_id}-{type(event).__name__}",
    )


async def _ingress_dispatch_shard_drop(bot: Bot, event: Event) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    if await should_skip_ingress_dispatch_for_bot(int(bot.self_id), event):
        logger.debug(
            "ingress_dispatch: drop duplicate group event bot={} group={} key_len={}",
            bot.self_id,
            event.group_id,
            len(event.get_plaintext()),
        )
        return True
    return False


async def _slow_worker() -> None:
    assert _slow_queue is not None
    while True:
        item = await _slow_queue.get()
        try:
            if item is None:
                break
            bot, event, enqueued_at = item
            wait_ms = (time.monotonic() - enqueued_at) * 1000.0
            if wait_ms >= _SLOW_QUEUE_WAIT_LOG_MS:
                logger.debug(
                    "ingress_dispatch: slow queue_wait_ms={:.0f} bot={} type={}",
                    wait_ms,
                    bot.self_id,
                    type(event).__name__,
                )
            if not await acquire_slow_event_slot(event):
                logger.debug(
                    "ingress_dispatch: drop slow event (saturated at worker) type={}",
                    type(event).__name__,
                )
                continue
            try:
                await _run_handle_event(bot, event)
            finally:
                release_slow_event_slot(event)
        except Exception:
            logger.exception("ingress_dispatch: slow worker failed")
        finally:
            _slow_queue.task_done()


async def ingress_handle_event(bot: Bot, event: Event) -> None:
    """替换 nonebot.message.handle_event：命令/私聊异步直达，水群入队由 worker 消费。"""
    if _orig_handle_event is None:
        raise RuntimeError("ingress dispatch is not installed")
    if await _ingress_dispatch_shard_drop(bot, event):
        return

    if not ingress_fast_lane_enabled() or not should_apply_ingress_slow_path(event):
        _schedule_handle_event(bot, event)
        return

    queue = _slow_queue
    assert queue is not None
    try:
        queue.put_nowait((bot, event, time.monotonic()))
    except asyncio.QueueFull:
        logger.debug(
            "ingress_dispatch: drop slow event (queue full) type={}",
            type(event).__name__,
        )


def install_ingress_event_dispatch() -> None:
    global _orig_handle_event, _dispatch_installed
    if _dispatch_installed:
        return
    import nonebot.message as nb_message

    _orig_handle_event = nb_message.handle_event
    nb_message.handle_event = ingress_handle_event  # type: ignore[assignment]
    _dispatch_installed = True


def start_ingress_slow_dispatch_workers() -> None:
    global _slow_queue, _slow_worker_tasks
    if _slow_worker_tasks:
        return
    _slow_queue = asyncio.Queue(maxsize=_slow_queue_capacity())
    _slow_worker_tasks.extend(asyncio.create_task(_slow_worker()) for _ in range(_slow_worker_count()))


async def stop_ingress_slow_dispatch_workers() -> None:
    global _slow_queue, _slow_worker_tasks
    if not _slow_worker_tasks or _slow_queue is None:
        return
    for _ in _slow_worker_tasks:
        await _slow_queue.put(None)
    await asyncio.gather(*_slow_worker_tasks, return_exceptions=True)
    _slow_worker_tasks = []
    _slow_queue = None


async def reload_ingress_dispatch_runtime() -> None:
    """WebUI 保存入站门控后：重读 .env、重建慢路径槽与 dispatch worker。"""
    clear_ingress_config_cache()
    clear_ingress_slow_path_runtime_state()
    await stop_ingress_slow_dispatch_workers()
    if ingress_fast_lane_enabled():
        start_ingress_slow_dispatch_workers()
    cfg = get_ingress_config()
    logger.info(
        "ingress runtime reloaded: fast_lane={} slow_concurrency={} slow_overflow={} "
        "slow_drop={} dispatch_workers={} dispatch_queue_max={}",
        cfg.ingress_fast_lane_enabled,
        cfg.ingress_slow_concurrency,
        cfg.ingress_slow_overflow_concurrency,
        cfg.ingress_slow_drop_on_timeout,
        slow_dispatch_worker_count() if cfg.ingress_fast_lane_enabled else 0,
        slow_dispatch_queue_capacity() if cfg.ingress_fast_lane_enabled else 0,
    )
