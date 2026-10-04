from __future__ import annotations

import pytest


async def capture_work_service_workers(monkeypatch, *, concurrency, handlers, **kwargs):
    import asyncio

    from pallas.core.platform.work_jobs import service

    workers = []
    started = []
    shutdown = asyncio.Event()

    class Worker:
        def __init__(self, **options):
            workers.append(options)

        async def run_once(self):
            started.append(self)
            await shutdown.wait()
            return False

    async def wait_for_shutdown(_store, **_kwargs):
        await asyncio.Event().wait()

    async def init_db():
        return None

    monkeypatch.setattr("pallas.core.foundation.db.init_db", init_db)
    monkeypatch.setattr(service, "build_work_job_store", lambda **_kwargs: object())
    monkeypatch.setattr(service, "WorkJobWorker", Worker)
    monkeypatch.setattr(service, "work_aux_concurrency", lambda: concurrency)
    monkeypatch.setattr(service, "run_work_status_publisher", wait_for_shutdown)
    task = asyncio.create_task(service.run_work_service(handlers, **kwargs))
    try:
        for _ in range(50):
            if workers and len(started) == len(workers):
                break
            await asyncio.sleep(0)
    finally:
        shutdown.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return workers


def test_work_aux_concurrency_uses_configured_value_with_pg_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs import service

    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        lambda key: "12" if key == "PALLAS_WORK_AUX_CONCURRENCY" else None,
    )
    monkeypatch.setattr(
        "pallas.core.foundation.db.pool_budget.cap_by_pg_pool",
        lambda requested, workload_fraction: min(requested, 3),
    )

    assert service.work_aux_concurrency() == 3


def test_work_aux_batch_sizes_preserve_total_concurrency() -> None:
    from pallas.core.platform.work_jobs import service

    assert service.work_aux_batch_sizes(3) == [3]
    assert service.work_aux_batch_sizes(4) == [4]
    assert service.work_aux_batch_sizes(5) == [3, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2, 3, 4, 5, 32])
async def test_work_service_partitions_short_jobs_without_increasing_capacity(
    monkeypatch: pytest.MonkeyPatch, concurrency: int
) -> None:
    async def handler(_payload):
        return None

    excluded = frozenset({"bot_action.send"})
    priorities = (frozenset({"repeater.message"}), frozenset({"repeater.learn"}))
    workers = await capture_work_service_workers(
        monkeypatch,
        concurrency=concurrency,
        handlers={
            "repeater.message": handler,
            "repeater.learn": handler,
            "image_cache.capture": handler,
            "group.insight": handler,
            "external.kind": handler,
        },
        exclude_kinds=excluded,
        priority_tiers=priorities,
    )

    assert sum(worker["batch_size"] for worker in workers) == concurrency
    short_workers = [worker for worker in workers if worker.get("kinds") is not None]
    other_workers = [worker for worker in workers if worker.get("kinds") is None]
    if concurrency == 1:
        assert len(workers) == 1
        assert workers[0]["priority_tiers"] is None
        assert workers[0]["exclude_kinds"] == excluded
        return

    assert short_workers
    assert other_workers
    assert {kind for worker in short_workers for kind in worker["kinds"]} == {
        "repeater.message",
        "repeater.learn",
        "image_cache.capture",
    }
    assert all(worker["priority_tiers"] is None for worker in short_workers)
    assert all(worker["exclude_kinds"] == excluded for worker in short_workers)
    assert all(
        worker["exclude_kinds"] == excluded | {"repeater.message", "repeater.learn", "image_cache.capture"}
        for worker in other_workers
    )
    assert all(worker["priority_tiers"] == priorities for worker in other_workers)
    assert all(worker["kinds"] is None for worker in other_workers)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handlers", "excluded", "expect_unpartitioned_priority"),
    [
        ({"group.insight": None}, frozenset(), True),
        ({"repeater.message": None}, frozenset(), False),
        ({"repeater.message": None, "image_cache.capture": None}, frozenset(), False),
        ({}, frozenset(), True),
        ({"repeater.message": None, "group.insight": None}, frozenset({"repeater.message"}), True),
        ({"repeater.message": None, "group.insight": None}, frozenset({"group.insight"}), False),
    ],
)
async def test_work_service_does_not_reserve_an_empty_lane(
    monkeypatch: pytest.MonkeyPatch, handlers: dict, excluded: frozenset[str], expect_unpartitioned_priority: bool
) -> None:
    async def handler(_payload):
        return None

    workers = await capture_work_service_workers(
        monkeypatch,
        concurrency=4,
        handlers=dict.fromkeys(handlers, handler),
        exclude_kinds=excluded,
        priority_tiers=(frozenset({"repeater.message"}),),
    )

    assert sum(worker["batch_size"] for worker in workers) == 4
    assert all(worker.get("kinds") is None for worker in workers)
    assert all(worker["exclude_kinds"] == excluded for worker in workers)
    if expect_unpartitioned_priority:
        assert all(worker["priority_tiers"] == (frozenset({"repeater.message"}),) for worker in workers)
    else:
        assert all(worker["priority_tiers"] is None for worker in workers)


@pytest.mark.asyncio
async def test_work_service_keeps_short_jobs_moving_while_group_insight_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from types import SimpleNamespace

    from pallas.core.platform.work_jobs import service
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.shared.utils import media_cache

    store = MemoryWorkJobStore()
    group_started = asyncio.Event()
    release_group = asyncio.Event()
    message_finished = asyncio.Event()
    image_inserted = asyncio.Event()
    active = 0
    max_active = 0

    async def track_start() -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)

    async def track_end() -> None:
        nonlocal active
        active -= 1

    async def group_handler(_payload):
        await track_start()
        group_started.set()
        try:
            await release_group.wait()
        finally:
            await track_end()

    async def message_handler(payload):
        await track_start()
        try:
            if payload.get("id") == "first":
                for index in range(20):
                    await store.enqueue(
                        WorkJob.create(
                            kind="repeater.message",
                            payload={"id": f"tail-{index}"},
                            idempotency_key=f"message:tail:{index}",
                        )
                    )
            await asyncio.sleep(0.02)
            message_finished.set()
        finally:
            await track_end()

    class ImageRepository:
        async def find_by_cq_code(self, _cq_code):
            return None

        async def insert(self, _image):
            image_inserted.set()

    async def fetch_image(_url):
        return b"image", 200

    async def image_handler(payload):
        await track_start()
        try:
            await media_cache.handle_image_cache_capture(payload)
        finally:
            await track_end()

    monkeypatch.setattr(media_cache, "time", SimpleNamespace(time=lambda: 1000.0))
    monkeypatch.setattr(media_cache, "image_cache_repo", ImageRepository())
    monkeypatch.setattr(media_cache, "_fetch_image_bytes", fetch_image)

    await store.enqueue(WorkJob.create(kind="group.insight", payload={}, idempotency_key="insight:blocked"))
    await store.enqueue(
        WorkJob.create(kind="repeater.message", payload={"id": "first"}, idempotency_key="message:first")
    )
    await store.enqueue(
        WorkJob.create(
            kind="image_cache.capture",
            payload={
                "cq_code": "[CQ:image,file=fresh.image]",
                "url": "https://example.com/fresh.png",
                "created_at": 1000.0,
            },
            idempotency_key="image:fresh",
        )
    )

    async def init_db():
        return None

    async def wait_for_shutdown(_store, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr("pallas.core.foundation.db.init_db", init_db)
    monkeypatch.setattr(service, "build_work_job_store", lambda **_kwargs: store)
    monkeypatch.setattr(service, "work_aux_concurrency", lambda: 2)
    monkeypatch.setattr(service, "run_work_status_publisher", wait_for_shutdown)
    monkeypatch.setattr(service, "_IDLE_BACKOFF_BASE_SEC", 0.001)
    monkeypatch.setattr(service, "_IDLE_BACKOFF_MAX_SEC", 0.01)

    task = asyncio.create_task(
        service.run_work_service(
            {
                "group.insight": group_handler,
                "repeater.message": message_handler,
                "image_cache.capture": image_handler,
            },
            exclude_kinds=frozenset({"bot_action.send"}),
            priority_tiers=(frozenset({"repeater.message"}),),
            handler_timeout_sec=60,
        )
    )
    try:
        await asyncio.wait_for(group_started.wait(), timeout=0.5)
        await asyncio.wait_for(message_finished.wait(), timeout=0.5)
        await asyncio.wait_for(image_inserted.wait(), timeout=0.15)
        assert not release_group.is_set()
        assert max_active == 2
    finally:
        release_group.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [2, 3, 5])
async def test_work_service_reserves_short_capacity_and_cleans_up_all_pools(
    monkeypatch: pytest.MonkeyPatch, concurrency: int
) -> None:
    import asyncio

    from pallas.core.platform.work_jobs import service
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    other_capacity = concurrency // 2
    long_started = asyncio.Event()
    short_started = asyncio.Event()
    blocked = asyncio.Event()
    active_long = active = peak = 0
    completed_short = 0

    async def long_handler(_payload):
        nonlocal active_long, active, peak
        active_long += 1
        active += 1
        peak = max(peak, active)
        if active_long == other_capacity:
            long_started.set()
        try:
            await blocked.wait()
        finally:
            active_long -= 1
            active -= 1

    async def short_handler(_payload):
        nonlocal active, peak, completed_short
        active += 1
        peak = max(peak, active)
        try:
            # Keep short work arriving while every long-task slot is occupied.
            await store.enqueue(
                WorkJob.create(kind="repeater.message", payload={}, idempotency_key=f"short:{completed_short + 1}")
            )
            completed_short += 1
            if long_started.is_set():
                short_started.set()
            await asyncio.sleep(0)
        finally:
            active -= 1

    for index in range(concurrency * 2):
        await store.enqueue(WorkJob.create(kind="group.insight", payload={}, idempotency_key=f"long:{index}"))
    await store.enqueue(WorkJob.create(kind="repeater.message", payload={}, idempotency_key="short:0"))

    async def init_db():
        return None

    async def status_publisher(_store, **_kwargs):
        await blocked.wait()

    monkeypatch.setattr("pallas.core.foundation.db.init_db", init_db)
    monkeypatch.setattr(service, "build_work_job_store", lambda **_kwargs: store)
    monkeypatch.setattr(service, "work_aux_concurrency", lambda: concurrency)
    monkeypatch.setattr(service, "run_work_status_publisher", status_publisher)
    existing_tasks = asyncio.all_tasks()
    task = asyncio.create_task(
        service.run_work_service({"group.insight": long_handler, "repeater.message": short_handler})
    )
    try:
        await asyncio.wait_for(long_started.wait(), timeout=1)
        await asyncio.wait_for(short_started.wait(), timeout=1)
        assert active_long == other_capacity
        assert completed_short > 0
        assert peak <= concurrency
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert active == 0
    assert not [child for child in asyncio.all_tasks() - existing_tasks if not child.done()]


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_child", ["consumer", "publisher"])
async def test_work_service_joins_sibling_pools_when_child_fails(
    monkeypatch: pytest.MonkeyPatch, failing_child: str
) -> None:
    import asyncio

    from pallas.core.platform.work_jobs import service

    started: set[str] = set()
    cleaned: set[str] = set()
    all_started = asyncio.Event()
    never = asyncio.Event()

    class Worker:
        def __init__(self, **options):
            self.owner = options["owner"]

    async def child(name: str) -> None:
        started.add(name)
        if len(started) == 3:
            all_started.set()
        try:
            await all_started.wait()
            if name == failing_child or name == f"{failing_child}-0":
                raise RuntimeError("test child failure")
            await never.wait()
        finally:
            cleaned.add(name)

    async def init_db():
        return None

    async def run_consumer(worker):
        index = worker.owner.rsplit(":", maxsplit=1)[-1]
        await child(f"consumer-{index}")

    async def status_publisher(_store, **_kwargs):
        await child("publisher")

    async def handler(_payload):
        return None

    monkeypatch.setattr("pallas.core.foundation.db.init_db", init_db)
    monkeypatch.setattr(service, "build_work_job_store", lambda **_kwargs: object())
    monkeypatch.setattr(service, "WorkJobWorker", Worker)
    monkeypatch.setattr(service, "work_aux_concurrency", lambda: 2)
    monkeypatch.setattr(service, "run_work_consumer", run_consumer)
    monkeypatch.setattr(service, "run_work_status_publisher", status_publisher)

    existing_tasks = asyncio.all_tasks()
    with pytest.raises(ExceptionGroup):
        await service.run_work_service({"group.insight": handler, "repeater.message": handler})

    assert started == {"consumer-0", "consumer-1", "publisher"}
    assert cleaned == started
    assert not [task for task in asyncio.all_tasks() - existing_tasks if not task.done()]


@pytest.mark.asyncio
async def test_work_service_initializes_database_before_building_store(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from pallas.core.platform.work_jobs import service

    steps: list[str] = []
    service_task: asyncio.Task | None = None

    async def init_db() -> None:
        steps.append("db")

    class Worker:
        async def run_once(self) -> bool:
            steps.append("run")
            service_task.cancel()
            await asyncio.Event().wait()

    monkeypatch.setattr("pallas.core.foundation.db.init_db", init_db)
    monkeypatch.setattr(service, "build_work_job_store", lambda **_kwargs: steps.append("store"))
    monkeypatch.setattr(service, "WorkJobWorker", lambda **_kwargs: Worker())
    monkeypatch.setattr(service, "work_aux_concurrency", lambda: 1)

    service_task = asyncio.create_task(service.run_work_service({}))
    with pytest.raises(asyncio.CancelledError):
        await service_task

    assert steps == ["db", "store", "run"]


@pytest.mark.asyncio
async def test_work_consumer_idle_backoff_slows_idle_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from pallas.core.platform.work_jobs import service

    class Worker:
        def __init__(self) -> None:
            self.count = 0

        async def run_once(self) -> bool:
            self.count += 1
            return False

    async def collect(worker: Worker, idle_backoff: bool, seconds: float) -> int:
        task = asyncio.create_task(service.run_work_consumer(worker, idle_backoff=idle_backoff))
        try:
            await asyncio.sleep(seconds)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return worker.count

    monkeypatch.setattr(service, "_IDLE_BACKOFF_MAX_SEC", 2.0)
    monkeypatch.setattr(service, "_IDLE_BACKOFF_BASE_SEC", 0.1)

    fast = await collect(Worker(), idle_backoff=False, seconds=0.5)
    slow = await collect(Worker(), idle_backoff=True, seconds=0.5)

    assert fast > slow
    assert slow >= 1


@pytest.mark.asyncio
async def test_idle_backoff_caps_exponent_to_avoid_overflow() -> None:
    from pallas.core.platform.work_jobs import service

    assert service.idle_backoff_seconds(10**6) == service._IDLE_BACKOFF_MAX_SEC
    assert service.idle_backoff_seconds(0) == service._IDLE_BACKOFF_BASE_SEC
    assert service.idle_backoff_seconds(1) == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_work_consumer_survives_run_once_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from pallas.core.platform.work_jobs import service

    class Worker:
        def __init__(self) -> None:
            self.calls = 0

        async def run_once(self) -> bool:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return False

    worker = Worker()
    monkeypatch.setattr(service, "_IDLE_BACKOFF_BASE_SEC", 0.01)
    monkeypatch.setattr(service, "_IDLE_BACKOFF_MAX_SEC", 0.02)

    task = asyncio.create_task(service.run_work_consumer(worker))
    try:
        await asyncio.sleep(0.08)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert worker.calls >= 2
