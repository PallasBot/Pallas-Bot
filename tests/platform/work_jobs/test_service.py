from __future__ import annotations

import pytest


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

    with pytest.raises(asyncio.CancelledError):
        await service.run_work_service({})

    assert steps == ["db", "store", "run"]
