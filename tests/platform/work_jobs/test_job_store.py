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
async def test_memory_store_requeue_terminal_only_reactivates_terminal_jobs() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    job = WorkJob.create(kind="test", payload={}, idempotency_key="test:requeue-terminal")

    first, reactivated = await store.requeue_terminal(job)
    assert first == job
    assert reactivated is True

    pending, reactivated = await store.requeue_terminal(job)
    assert pending == job
    assert reactivated is False

    leased = await store.claim(owner="worker", lease_sec=1)
    assert leased is not None
    active, reactivated = await store.requeue_terminal(job)
    assert active.id == job.id
    assert reactivated is False

    assert await store.complete(job_id=leased.id, owner="worker", lease_id=leased.lease_id or "")
    replacement = WorkJob.create(kind="test", payload={"retry": True}, idempotency_key=job.idempotency_key)
    revived, reactivated = await store.requeue_terminal(replacement)

    assert revived == replacement
    assert reactivated is True


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
        "dead_lettered": 0,
        "oldest_pending_age_sec": None,
        "max_attempts": 1,
    }


@pytest.mark.asyncio
async def test_memory_store_claim_many_leases_oldest_jobs_in_one_call() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    first = await store.enqueue(WorkJob.create(kind="test", payload={"id": 1}, idempotency_key="test:claim:1"))
    second = await store.enqueue(WorkJob.create(kind="test", payload={"id": 2}, idempotency_key="test:claim:2"))
    await store.enqueue(WorkJob.create(kind="test", payload={"id": 3}, idempotency_key="test:claim:3"))

    claimed = await store.claim_many(owner="worker", lease_sec=1, limit=2)

    assert [job.id for job in claimed] == [first.id, second.id]
    assert [job.attempts for job in claimed] == [1, 1]


@pytest.mark.asyncio
async def test_memory_store_complete_many_releases_a_claimed_batch() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:complete:1"))
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:complete:2"))
    claimed = await store.claim_many(owner="worker", lease_sec=1, limit=2)

    assert await store.complete_many(jobs=claimed, owner="worker") == 2
    assert await store.claim_many(owner="other", lease_sec=1, limit=2) == []


@pytest.mark.asyncio
async def test_memory_store_does_not_complete_a_reclaimed_lease() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:fence"))
    first = await store.claim(owner="worker-a", lease_sec=0.01)
    assert first is not None

    await asyncio.sleep(0.02)
    second = await store.claim(owner="worker-b", lease_sec=1)
    assert second is not None

    assert await store.complete_many(jobs=[first], owner="worker-a") == 0
    assert await store.complete_many(jobs=[second], owner="worker-b") == 1


@pytest.mark.asyncio
async def test_memory_store_complete_retains_configured_kind_as_terminal() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore(completion_retention={"sticker_vision.select": "done"})
    job = WorkJob.create(kind="sticker_vision.select", payload={"mock": 1}, idempotency_key="s:v:retain:1")
    await store.enqueue(job)
    claimed = await store.claim(owner="worker", lease_sec=1)
    assert claimed is not None

    assert await store.complete(job_id=claimed.id, owner="worker", lease_id=claimed.lease_id or "")

    # 完成后仍可读到该任务，state 反映完成态
    after = store._jobs[claimed.id]
    assert after.kind == "sticker_vision.select"
    assert store._completed == set()  # 完成保留不再放入 _completed 以免被 requeue 复活


@pytest.mark.asyncio
async def test_memory_store_retained_terminal_cannot_be_requeued() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore(completion_retention={"sticker_vision.select": "done"})
    job = WorkJob.create(kind="sticker_vision.select", payload={}, idempotency_key="s:v:req:1")
    await store.enqueue(job)
    leased = await store.claim(owner="worker", lease_sec=1)
    assert leased is not None
    await store.complete(job_id=leased.id, owner="worker", lease_id=leased.lease_id or "")

    replacement = WorkJob.create(kind="sticker_vision.select", payload={}, idempotency_key="s:v:req:1")
    _, reactivated = await store.requeue_terminal(replacement)
    assert reactivated is False
