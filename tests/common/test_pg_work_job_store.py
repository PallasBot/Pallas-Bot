from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_requeue_terminal_is_single_flight_for_concurrent_postgres_producers(pg_engine) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.pg_store import PostgresWorkJobStore

    store = PostgresWorkJobStore()

    def new_job() -> WorkJob:
        return WorkJob.create(kind="sticker.label.visual", payload={}, idempotency_key="label:concurrent:1")

    first, second = await asyncio.gather(store.requeue_terminal(new_job()), store.requeue_terminal(new_job()))

    assert first[0].id == second[0].id
    assert sorted((first[1], second[1])) == [False, True]
    claimed = await store.claim(owner="worker", lease_sec=30)
    assert claimed is not None
    assert await store.claim(owner="other", lease_sec=30) is None
    assert await store.complete(job_id=claimed.id, owner="worker", lease_id=claimed.lease_id or "")

    reactivated, competing = await asyncio.gather(store.requeue_terminal(new_job()), store.requeue_terminal(new_job()))

    assert reactivated[0].id == competing[0].id == first[0].id
    assert sorted((reactivated[1], competing[1])) == [False, True]
