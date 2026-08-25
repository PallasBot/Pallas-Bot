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
    priority_kinds: frozenset[str] | None = None,
    handler_timeout_sec: float | None = None,
) -> None:
    from pallas.core.foundation.db import init_db

    await init_db()
    store = build_work_job_store()
    concurrency = work_aux_concurrency()
    handler_timeout_sec = work_handler_timeout_sec(handler_timeout_sec)
    owner_prefix = f"{socket.gethostname()}:{os.getpid()}"
    batch_sizes = work_aux_batch_sizes(concurrency)
    from .observability import WorkAuxRuntimeMetrics

    metrics = WorkAuxRuntimeMetrics()
    workers = [
        WorkJobWorker(
            store=store,
            owner=f"{owner_prefix}:{index}",
            handlers=handlers,
            batch_size=batch_size,
            metrics=metrics,
            exclude_kinds=exclude_kinds,
            priority_kinds=priority_kinds,
            handler_timeout_sec=handler_timeout_sec,
        )
        for index, batch_size in enumerate(batch_sizes)
    ]
    logger.info(
        "Work auxiliary service started with handlers [{}], consumers [{}], excluded kinds [{}], "
        "and priority kinds [{}].",
        sorted(handlers),
        concurrency,
        sorted(exclude_kinds) if exclude_kinds else None,
        sorted(priority_kinds) if priority_kinds else None,
    )
    await asyncio.gather(
        *(run_work_consumer(worker) for worker in workers),
        run_work_status_publisher(store, consumers=concurrency, metrics=metrics),
    )
