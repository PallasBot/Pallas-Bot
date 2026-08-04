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
