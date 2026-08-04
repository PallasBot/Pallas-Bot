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
