from __future__ import annotations

import pytest


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
async def test_work_service_initializes_database_before_building_store(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs import service

    steps: list[str] = []

    async def init_db() -> None:
        steps.append("db")

    class Worker:
        async def run_once(self) -> bool:
            steps.append("run")
            raise asyncio.CancelledError

    import asyncio

    monkeypatch.setattr("pallas.core.foundation.db.init_db", init_db)
    monkeypatch.setattr(service, "build_work_job_store", lambda **_kwargs: steps.append("store"))
    monkeypatch.setattr(service, "WorkJobWorker", lambda **_kwargs: Worker())
    monkeypatch.setattr(service, "work_aux_concurrency", lambda: 1)

    with pytest.raises(asyncio.CancelledError):
        await service.run_work_service({})

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
