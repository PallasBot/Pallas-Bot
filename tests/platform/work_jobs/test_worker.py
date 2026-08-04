from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_worker_completes_a_claimed_job() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={"value": 1}, idempotency_key="test:1"))
    seen: list[dict] = []

    async def handler(payload: dict) -> None:
        seen.append(payload)

    worker = WorkJobWorker(store=store, owner="test-worker", handlers={"test": handler})
    assert await worker.run_once() is True
    assert seen == [{"value": 1}]
    assert await store.claim(owner="other", lease_sec=1) is None


@pytest.mark.asyncio
async def test_worker_requeues_a_failed_job() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:2"))

    async def handler(_payload: dict) -> None:
        raise RuntimeError("retry")

    worker = WorkJobWorker(store=store, owner="test-worker", handlers={"test": handler}, retry_after_sec=0)
    assert await worker.run_once() is True
    assert (await store.claim(owner="other", lease_sec=1)).attempts == 2


@pytest.mark.asyncio
async def test_worker_renews_lease_while_handler_is_running() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:renew"))
    claimed_by_other: list[object] = []

    async def handler(_payload: dict) -> None:
        await asyncio.sleep(1.05)
        claimed_by_other.append(await store.claim(owner="other", lease_sec=1))

    worker = WorkJobWorker(store=store, owner="test-worker", handlers={"test": handler}, lease_sec=1)

    assert await worker.run_once() is True
    assert claimed_by_other == [None]


@pytest.mark.asyncio
async def test_worker_runs_claimed_batch_concurrently_and_acknowledges_it() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={"id": 1}, idempotency_key="test:batch-worker:1"))
    await store.enqueue(WorkJob.create(kind="test", payload={"id": 2}, idempotency_key="test:batch-worker:2"))
    release = asyncio.Event()
    started = 0

    async def handler(_payload: dict) -> None:
        nonlocal started
        started += 1
        await release.wait()

    worker = WorkJobWorker(store=store, owner="test-worker", handlers={"test": handler}, batch_size=2)
    task = asyncio.create_task(worker.run_once())
    for _ in range(20):
        if started == 2:
            break
        await asyncio.sleep(0.01)
    release.set()

    assert await task is True
    assert started == 2
    assert await store.claim_many(owner="other", lease_sec=1, limit=2) == []
