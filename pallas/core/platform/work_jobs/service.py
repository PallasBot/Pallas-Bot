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


async def run_work_consumer(worker: WorkJobWorker) -> None:
    while True:
        if not await worker.run_once():
            await asyncio.sleep(0.2)


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
) -> None:
    from pallas.core.foundation.db import init_db

    await init_db()
    store = build_work_job_store()
    concurrency = work_aux_concurrency()
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
        )
        for index, batch_size in enumerate(batch_sizes)
    ]
    logger.info(
        "work aux started handlers={} consumers={} exclude_kinds={} priority_kinds={}",
        sorted(handlers),
        concurrency,
        sorted(exclude_kinds) if exclude_kinds else None,
        sorted(priority_kinds) if priority_kinds else None,
    )
    await asyncio.gather(
        *(run_work_consumer(worker) for worker in workers),
        run_work_status_publisher(store, consumers=concurrency, metrics=metrics),
    )
