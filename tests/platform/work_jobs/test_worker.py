from __future__ import annotations

import asyncio

import pytest

from pallas.api.runtime import DirectBotAction, DirectWorkResult


@pytest.mark.asyncio
async def test_worker_completes_a_claimed_job() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.observability import WorkAuxRuntimeMetrics
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={"value": 1}, idempotency_key="test:1"))
    seen: list[dict] = []

    async def handler(payload: dict) -> None:
        seen.append(payload)

    metrics = WorkAuxRuntimeMetrics()
    worker = WorkJobWorker(store=store, owner="test-worker", handlers={"test": handler}, metrics=metrics)
    assert await worker.run_once() is True
    assert seen == [{"value": 1}]
    assert await store.claim(owner="other", lease_sec=1) is None
    assert metrics.snapshot() == {
        "completed_since_start": 1,
        "failed_since_start": 0,
        "retried_since_start": 0,
        "dead_lettered_since_start": 0,
    }


@pytest.mark.asyncio
async def test_worker_commits_a_handler_result_before_completing_the_job() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:result"))
    result = DirectWorkResult(
        actions=(DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "hello"}),)
    )
    result_committer = SimpleResultCommitter()

    async def handler(_payload: dict) -> DirectWorkResult:
        return result

    worker = WorkJobWorker(
        store=store,
        owner="test-worker",
        handlers={"test": handler},
        result_committer=result_committer,
    )

    assert await worker.run_once() is True
    assert result_committer.results == [result]
    assert result_committer.committed[0][0] == "test"
    assert result_committer.committed[0][1]
    assert await store.claim(owner="other", lease_sec=1) is None


@pytest.mark.asyncio
async def test_worker_dead_letters_when_result_commit_fails() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.result_committer import WorkResultCommitError
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:result-failure"))
    result = DirectWorkResult(
        actions=(DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "hello"}),)
    )
    result_committer = SimpleResultCommitter(error=WorkResultCommitError("delivery failed"))

    async def handler(_payload: dict) -> DirectWorkResult:
        return result

    worker = WorkJobWorker(
        store=store,
        owner="test-worker",
        handlers={"test": handler},
        result_committer=result_committer,
        retry_after_sec=0,
    )

    assert await worker.run_once() is True
    assert result_committer.results == [result]
    assert await store.claim(owner="other", lease_sec=1) is None
    assert (await store.stats())["dead_lettered"] == 1


@pytest.mark.asyncio
async def test_worker_handler_timeout_requeues_and_frees_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.observability import WorkAuxRuntimeMetrics
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:timeout"))

    async def handler(_payload: dict) -> None:
        await asyncio.Event().wait()

    metrics = WorkAuxRuntimeMetrics()
    worker = WorkJobWorker(
        store=store,
        owner="test-worker",
        handlers={"test": handler},
        handler_timeout_sec=0.05,
        retry_after_sec=0,
        metrics=metrics,
    )

    assert await worker.run_once() is True
    assert metrics.snapshot() == {
        "completed_since_start": 0,
        "failed_since_start": 1,
        "retried_since_start": 1,
        "dead_lettered_since_start": 0,
    }
    reclaimed = await store.claim(owner="replacement", lease_sec=1)
    assert reclaimed is not None
    assert reclaimed.attempts == 2


class SimpleResultCommitter:
    def __init__(self, error: Exception | None = None) -> None:
        self.results: list[DirectWorkResult] = []
        self.committed: list[tuple[str, str]] = []
        self.error = error

    async def commit(
        self,
        result: DirectWorkResult,
        *,
        job_kind: str = "",
        job_id: str = "",
    ) -> bool:
        self.results.append(result)
        self.committed.append((job_kind, job_id))
        if self.error is not None:
            raise self.error
        return True


@pytest.mark.asyncio
async def test_worker_requeues_a_failed_job() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.observability import WorkAuxRuntimeMetrics
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:2"))

    async def handler(_payload: dict) -> None:
        raise RuntimeError("retry")

    metrics = WorkAuxRuntimeMetrics()
    worker = WorkJobWorker(
        store=store,
        owner="test-worker",
        handlers={"test": handler},
        retry_after_sec=0,
        metrics=metrics,
    )
    assert await worker.run_once() is True
    assert (await store.claim(owner="other", lease_sec=1)).attempts == 2
    assert metrics.snapshot() == {
        "completed_since_start": 0,
        "failed_since_start": 1,
        "retried_since_start": 1,
        "dead_lettered_since_start": 0,
    }


@pytest.mark.asyncio
async def test_worker_dead_letters_job_after_max_attempts() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.observability import WorkAuxRuntimeMetrics
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:dead-letter"))

    async def handler(_payload: dict) -> None:
        raise RuntimeError("permanent failure")

    metrics = WorkAuxRuntimeMetrics()
    worker = WorkJobWorker(store=store, owner="worker", handlers={"test": handler}, max_attempts=1, metrics=metrics)
    assert await worker.run_once() is True
    assert await store.claim(owner="other", lease_sec=1) is None
    assert (await store.stats())["dead_lettered"] == 1
    assert metrics.snapshot() == {
        "completed_since_start": 0,
        "failed_since_start": 1,
        "retried_since_start": 0,
        "dead_lettered_since_start": 1,
    }


@pytest.mark.asyncio
async def test_worker_requeues_unknown_job_kind() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="new-kind", payload={}, idempotency_key="test:unknown"))

    worker = WorkJobWorker(store=store, owner="old-worker", handlers={}, retry_after_sec=0)

    assert await worker.run_once() is True
    reclaimed = await store.claim(owner="new-worker", lease_sec=1)
    assert reclaimed is not None
    assert reclaimed.kind == "new-kind"
    assert reclaimed.attempts == 2


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
async def test_worker_cancels_handler_after_losing_its_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:lost-lease"))
    monkeypatch.setattr(store, "renew", lambda **_kwargs: asyncio.sleep(0, result=False))
    cancelled = asyncio.Event()

    async def handler(_payload: dict) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    worker = WorkJobWorker(store=store, owner="worker", handlers={"test": handler}, lease_sec=1, retry_after_sec=0)

    assert await worker.run_once() is True
    assert cancelled.is_set()
    assert await store.claim(owner="replacement", lease_sec=1) is not None


@pytest.mark.asyncio
async def test_worker_completes_handler_when_lease_check_finishes_in_same_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.observability import WorkAuxRuntimeMetrics
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="test", payload={}, idempotency_key="test:simultaneous-completion"))

    async def lost_lease(_self, _job) -> None:
        return None

    monkeypatch.setattr(WorkJobWorker, "_renew_lease", lost_lease)
    metrics = WorkAuxRuntimeMetrics()
    worker = WorkJobWorker(
        store=store,
        owner="worker",
        handlers={"test": lambda _payload: asyncio.sleep(0)},
        metrics=metrics,
    )

    assert await worker.run_once() is True
    assert await store.claim(owner="replacement", lease_sec=1) is None
    assert metrics.snapshot() == {
        "completed_since_start": 1,
        "failed_since_start": 0,
        "retried_since_start": 0,
        "dead_lettered_since_start": 0,
    }


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


@pytest.mark.asyncio
async def test_worker_refills_a_completed_slot_while_another_job_is_still_running() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = MemoryWorkJobStore()
    for job_id in ("slow", "fast", "next"):
        await store.enqueue(WorkJob.create(kind="test", payload={"id": job_id}, idempotency_key=f"test:{job_id}"))
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    next_started = asyncio.Event()

    async def handler(payload: dict) -> None:
        if payload["id"] == "slow":
            slow_started.set()
            await release_slow.wait()
        elif payload["id"] == "next":
            next_started.set()

    worker = WorkJobWorker(store=store, owner="test-worker", handlers={"test": handler}, batch_size=2)
    run_task = asyncio.create_task(worker.run_once())
    await slow_started.wait()
    try:
        await asyncio.wait_for(next_started.wait(), timeout=0.1)
    finally:
        release_slow.set()
        await run_task

    assert next_started.is_set()
