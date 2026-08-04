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
    monkeypatch.setattr(service, "build_work_job_store", lambda: steps.append("store"))
    monkeypatch.setattr(service, "WorkJobWorker", lambda **_kwargs: Worker())
    monkeypatch.setattr(service, "work_aux_concurrency", lambda: 1)

    with pytest.raises(asyncio.CancelledError):
        await service.run_work_service({})

    assert steps == ["db", "store", "run"]
