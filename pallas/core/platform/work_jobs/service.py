"""独立 work aux 的启动入口。"""

from __future__ import annotations

import asyncio
import math
import os
import socket
from typing import TYPE_CHECKING

from nonebot import logger

from .runtime import build_work_job_store
from .worker import WorkJobWorker

if TYPE_CHECKING:
    from .worker import WorkJobHandler


def work_aux_concurrency() -> int:
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value
    from pallas.core.foundation.db.pool_budget import cap_by_pg_pool

    raw = repo_env_raw_value("PALLAS_WORK_AUX_CONCURRENCY")
    try:
        requested = int(str(raw if raw is not None else "4").strip())
    except ValueError:
        requested = 4
    return cap_by_pg_pool(max(1, min(32, requested)), workload_fraction=0.15)


def work_aux_batch_sizes(concurrency: int) -> list[int]:
    total = max(1, int(concurrency))
    workers = math.ceil(total / 4)
    base, extra = divmod(total, workers)
    return [base + (1 if index < extra else 0) for index in range(workers)]


_WORK_HANDLER_TIMEOUT_DEFAULT_SEC = 600.0
_SHORT_WORK_KINDS = frozenset({"repeater.message", "repeater.learn", "image_cache.capture"})


def work_handler_timeout_sec(explicit: float | None) -> float | None:
    """handler 硬超时兜底：显式传入优先，其次读取 env，都无则用默认值。"""
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    if explicit is not None:
        return max(1.0, float(explicit))
    raw = repo_env_raw_value("PALLAS_WORK_HANDLER_TIMEOUT_SEC")
    if raw is None:
        return _WORK_HANDLER_TIMEOUT_DEFAULT_SEC
    try:
        parsed = float(str(raw).strip())
    except ValueError:
        logger.warning("Invalid PALLAS_WORK_HANDLER_TIMEOUT_SEC [{}], falling back to default.", raw)
        return _WORK_HANDLER_TIMEOUT_DEFAULT_SEC
    if parsed <= 0:
        return None
    return max(1.0, parsed)


_IDLE_BACKOFF_BASE_SEC = 0.2
_IDLE_BACKOFF_MAX_SEC = 2.0
_IDLE_BACKOFF_EXPONENT_CAP = 8


def idle_backoff_seconds(idle_rounds: int) -> float:
    exponent = min(idle_rounds, _IDLE_BACKOFF_EXPONENT_CAP)
    return min(_IDLE_BACKOFF_MAX_SEC, _IDLE_BACKOFF_BASE_SEC * (1.5**exponent))


async def run_work_consumer(worker: WorkJobWorker, *, idle_backoff: bool = True) -> None:
    idle_rounds = 0
    while True:
        try:
            polled = await worker.run_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("work aux consumer loop crashed, will retry: {}", exc)
            polled = False
            idle_rounds = 0
        if polled:
            idle_rounds = 0
            continue
        idle_rounds += 1
        if not idle_backoff:
            await asyncio.sleep(_IDLE_BACKOFF_BASE_SEC)
            continue
        await asyncio.sleep(idle_backoff_seconds(idle_rounds))


async def run_work_status_publisher(store, *, consumers: int, metrics) -> None:
    from .observability import write_work_aux_status

    while True:
        try:
            from pallas.core.platform.federate.ingress_audit import federate_ingress_audit_summary_sync

            runtime_metrics = metrics.snapshot()
            runtime_metrics.update(await asyncio.to_thread(federate_ingress_audit_summary_sync))
            write_work_aux_status(consumers=consumers, stats=await store.stats(), runtime_metrics=runtime_metrics)
        except Exception as exc:
            logger.warning("work aux status publish failed: {}", exc)
        await asyncio.sleep(5.0)


async def run_work_service(
    handlers: dict[str, WorkJobHandler],
    *,
    exclude_kinds: frozenset[str] | None = None,
    priority_tiers: tuple[frozenset[str], ...] | None = None,
    handler_timeout_sec: float | None = None,
) -> None:
    from pallas.core.foundation.db import init_db
    from pallas.core.platform.work_jobs import pg_notify

    await init_db()
    store = build_work_job_store(
        completion_retention={"sticker_vision.select": "done"},
        notify_completed=pg_notify.notify_delivery_ready,
    )
    concurrency = work_aux_concurrency()
    handler_timeout_sec = work_handler_timeout_sec(handler_timeout_sec)
    owner_prefix = f"{socket.gethostname()}:{os.getpid()}"
    batch_sizes = work_aux_batch_sizes(concurrency)
    excluded = exclude_kinds or frozenset()
    short_kinds = _SHORT_WORK_KINDS.intersection(handlers).difference(excluded)
    other_handler_kinds = frozenset(handlers).difference(short_kinds, excluded)
    if concurrency > 1 and short_kinds and other_handler_kinds:
        short_capacity = (concurrency + 1) // 2
        other_capacity = concurrency - short_capacity
        worker_specs = [
            (batch_size, short_kinds, exclude_kinds, None) for batch_size in work_aux_batch_sizes(short_capacity)
        ] + [
            (batch_size, None, frozenset(excluded | short_kinds), priority_tiers)
            for batch_size in work_aux_batch_sizes(other_capacity)
        ]
    else:
        # Without two populated lanes, keep all capacity together and use FIFO
        # whenever short jobs are present to avoid strict-priority starvation.
        worker_priorities = None if short_kinds else priority_tiers
        worker_specs = [(batch_size, None, exclude_kinds, worker_priorities) for batch_size in batch_sizes]

    from .observability import WorkAuxRuntimeMetrics

    metrics = WorkAuxRuntimeMetrics()
    workers = [
        WorkJobWorker(
            store=store,
            owner=f"{owner_prefix}:{index}",
            handlers=handlers,
            batch_size=batch_size,
            metrics=metrics,
            kinds=kinds,
            exclude_kinds=worker_excluded,
            priority_tiers=worker_priorities,
            handler_timeout_sec=handler_timeout_sec,
        )
        for index, (batch_size, kinds, worker_excluded, worker_priorities) in enumerate(worker_specs)
    ]
    logger.info(
        "Work auxiliary service started with handlers [{}], consumers [{}], excluded kinds [{}], "
        "and priority tiers [{}].",
        sorted(handlers),
        concurrency,
        sorted(exclude_kinds) if exclude_kinds else None,
        [sorted(tier) for tier in priority_tiers] if priority_tiers else None,
    )
    async with asyncio.TaskGroup() as task_group:
        for index, worker in enumerate(workers):
            task_group.create_task(run_work_consumer(worker), name=f"work_aux_consumer:{index}")
        task_group.create_task(
            run_work_status_publisher(store, consumers=concurrency, metrics=metrics),
            name="work_aux_status_publisher",
        )
