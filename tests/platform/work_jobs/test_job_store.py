from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_memory_store_deduplicates_and_releases_expired_leases() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    job = WorkJob.create(kind="repeater.learn", payload={"chat": {}}, idempotency_key="repeater.learn:1")

    first = await store.enqueue(job)
    second = await store.enqueue(job)

    assert first.id == second.id

    leased = await store.claim(owner="worker-a", lease_sec=0.01)
    assert leased is not None
    assert leased.id == first.id
    assert await store.claim(owner="worker-b", lease_sec=1) is None

    await asyncio.sleep(0.02)
    reclaimed = await store.claim(owner="worker-b", lease_sec=1)
    assert reclaimed is not None
    assert reclaimed.id == first.id
    assert reclaimed.attempts == 2


@pytest.mark.asyncio
async def test_memory_store_batch_enqueue_preserves_order_and_idempotency() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    first = WorkJob.create(kind="test", payload={"value": 1}, idempotency_key="test:batch:1")
    duplicate = WorkJob.create(kind="test", payload={"value": 2}, idempotency_key="test:batch:1")
    second = WorkJob.create(kind="test", payload={"value": 3}, idempotency_key="test:batch:2")

    written = await store.enqueue_many([first, duplicate, second])

    assert [job.id for job in written] == [first.id, first.id, second.id]
    assert [job.payload for job in written] == [{"value": 1}, {"value": 1}, {"value": 3}]


@pytest.mark.asyncio
async def test_memory_store_stats_reports_pending_leased_age_and_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    job = WorkJob.create(kind="test", payload={}, idempotency_key="test:stats")
    monkeypatch.setattr("pallas.core.platform.work_jobs.store.time.monotonic", lambda: 100.0)
    await store.enqueue(job)
    await store.claim(owner="worker", lease_sec=10)

    monkeypatch.setattr("pallas.core.platform.work_jobs.store.time.monotonic", lambda: 103.5)
    stats = await store.stats()

    assert stats == {
        "pending": 0,
        "leased": 1,
        "oldest_pending_age_sec": None,
        "max_attempts": 1,
    }
