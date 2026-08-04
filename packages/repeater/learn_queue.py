"""复读学习异步队列：handler 先接话，learn 后台限并发执行。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot import get_driver, logger

from pallas.core.platform.multi_bot.group import claim_group_message_event
from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.runtime import build_work_job_store

from .learn_runtime_config import get_repeater_learn_runtime_config

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

    from .model import Chat

_LEARN_PLUGIN = "repeater_learn"
_queue: asyncio.Queue[Chat] | None = None
_sem: asyncio.Semaphore | None = None
_sem_limit: int | None = None
_worker_tasks: list[asyncio.Task[None]] = []
_dropped_full: int = 0
_dropped_pressure: int = 0
_completed: int = 0
_learn_pool_wait_spins: int = 0
_LIFECYCLE_BOUND = False


def drain_learn_pause_stats() -> int:
    global _learn_pool_wait_spins
    spins = _learn_pool_wait_spins
    _learn_pool_wait_spins = 0
    return spins


async def wait_pg_pool_headroom_for_learn() -> None:
    global _learn_pool_wait_spins
    from pallas.core.foundation.db.pool_budget import pg_pool_under_pressure

    while pg_pool_under_pressure(threshold=0.25):
        _learn_pool_wait_spins += 1
        await asyncio.sleep(0.2)


def learn_queue_pressure_threshold() -> int:
    """队列到达该水位时优先保护接话，跳过新增 learn。"""
    # learn 队列一旦堆高，后续还会连带压住 image cache / corpus prefetch
    # 这里提前刹车，让主循环更快恢复，而不是把回填吞吐吃满。
    return max(64, learn_queue_max_size() // 16)


def learn_concurrency() -> int:
    from pallas.core.foundation.db.pool_budget import pg_pool_capacity

    requested = get_repeater_learn_runtime_config().learn_concurrency
    # learn 会持续制造本地写入、cache invalidate 与镜像回填，实际比普通后台 IO 更容易拖慢主循环。
    ceiling = max(1, int(pg_pool_capacity() * 0.03))
    return max(1, min(int(requested), ceiling))


def learn_queue_max_size() -> int:
    return get_repeater_learn_runtime_config().learn_queue_max_size


def clear_repeater_learn_runtime_state() -> None:
    """清信号量/队列缓存；配合 WebUI 热重载或 worker 重启。"""
    global _queue, _sem, _sem_limit
    _sem = None
    _sem_limit = None
    _queue = None


def learn_sem() -> asyncio.Semaphore:
    global _sem, _sem_limit
    limit = learn_concurrency()
    if _sem is None or _sem_limit != limit:
        _sem = asyncio.Semaphore(limit)
        _sem_limit = limit
    return _sem


def learn_queue() -> asyncio.Queue[Chat]:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue(maxsize=learn_queue_max_size())
    return _queue


def learn_queue_under_pressure() -> bool:
    return learn_queue().qsize() >= learn_queue_pressure_threshold()


def should_skip_repeater_learn_enqueue() -> bool:
    from pallas.core.foundation.db.pool_budget import pg_pool_under_pressure
    from pallas.core.platform.ingress.message_load import should_shed_chat_sidework

    if should_shed_chat_sidework():
        return True
    if pg_pool_under_pressure(threshold=0.25):
        return True
    return learn_queue_under_pressure()


async def run_learn_consumer() -> None:
    while True:
        chat = await learn_queue().get()
        try:
            await wait_pg_pool_headroom_for_learn()
            await execute_repeater_learn(chat)
        finally:
            learn_queue().task_done()


async def execute_repeater_learn(chat: Chat) -> None:
    global _completed
    try:
        ok = await chat.learn()
        if ok:
            _completed += 1
            from pallas.core.platform.ingress.hotpath_metrics import record_learn_completed

            record_learn_completed()
    except Exception as e:
        logger.warning(
            "repeater learn background failed bot={} group={}: {}",
            chat.chat_data.bot_id,
            chat.chat_data.group_id,
            e,
        )


async def enqueue_repeater_learn(chat: Chat, event: GroupMessageEvent) -> bool:
    """仅抢占成功的牛写入 durable outbox，实际学习在 work aux 执行。"""
    if not await claim_group_message_event(_LEARN_PLUGIN, event, int(event.self_id)):
        return False
    from .learner import Learner
    from .model import Chat

    payload = await Learner.capture_for_work(chat.chat_data, Chat._topics_lock, Chat._recent_topics)
    if payload is None:
        return False
    job = WorkJob.create(
        kind="repeater.learn",
        payload=payload.to_dict(),
        idempotency_key=f"repeater.learn:{int(event.group_id)}:{int(event.message_id)}:{int(event.self_id)}",
    )
    try:
        await build_work_job_store().enqueue(job)
    except Exception as exc:
        logger.warning(
            "repeater learn outbox enqueue failed bot={} group={} message={}: {}",
            event.self_id,
            event.group_id,
            event.message_id,
            exc,
        )
        return False
    from pallas.core.platform.ingress.hotpath_metrics import record_learn_enqueued

    record_learn_enqueued()
    return True


def _learn_workers_running() -> bool:
    return bool(_worker_tasks) and any(not t.done() for t in _worker_tasks)


async def start_repeater_learn_worker() -> None:
    global _worker_tasks
    if _learn_workers_running():
        return
    await stop_repeater_learn_worker()
    n = learn_concurrency()
    configured = get_repeater_learn_runtime_config().learn_concurrency
    if n < configured:
        from pallas.core.foundation.db.pool_budget import pg_pool_capacity

        logger.debug(
            "repeater learn concurrency capped by PG pool: effective={} configured={} pool={}",
            n,
            configured,
            pg_pool_capacity(),
        )
    _worker_tasks = [asyncio.create_task(run_learn_consumer(), name=f"repeater_learn_consumer_{i}") for i in range(n)]
    logger.debug(
        "repeater learn workers started: consumers={} queue_max={}",
        n,
        learn_queue_max_size(),
    )


async def stop_repeater_learn_worker() -> None:
    global _worker_tasks
    if not _worker_tasks:
        return
    tasks = list(_worker_tasks)
    _worker_tasks = []
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def reload_repeater_learn_worker_runtime() -> None:
    """WebUI 保存 learn 配置后：失效缓存并重启 worker。"""
    from .learn_runtime_config import clear_repeater_learn_runtime_config_cache

    clear_repeater_learn_runtime_config_cache()
    clear_repeater_learn_runtime_state()
    await stop_repeater_learn_worker()
    await start_repeater_learn_worker()
    logger.info(
        "repeater learn runtime reloaded: consumers={} queue_max={}",
        learn_concurrency(),
        learn_queue_max_size(),
    )


def bind_repeater_learn_lifecycle() -> None:
    global _LIFECYCLE_BOUND
    if _LIFECYCLE_BOUND:
        return
    _LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup():
        await start_repeater_learn_worker()

    @driver.on_shutdown
    async def _on_shutdown():
        await stop_repeater_learn_worker()
