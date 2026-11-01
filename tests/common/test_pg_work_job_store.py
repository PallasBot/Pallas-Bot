from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_requeue_terminal_is_single_flight_for_concurrent_postgres_producers(pg_engine) -> None:
    from sqlalchemy import select

    from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.pg_store import PostgresWorkJobStore

    store = PostgresWorkJobStore()

    def new_job() -> WorkJob:
        return WorkJob.create(kind="sticker.label.visual", payload={}, idempotency_key="label:concurrent:1")

    async def concurrently_requeue():
        jobs = [new_job(), new_job()]
        barrier = asyncio.Barrier(2)

        async def produce(job):
            await barrier.wait()
            return await store.requeue_terminal(job)

        result = await asyncio.gather(*(produce(job) for job in jobs))
        assert result[0][0].id == result[1][0].id
        assert result[0][0].id in {job.id for job in jobs}
        assert sorted(item[1] for item in result) == [False, True]
        async with get_session(read_only=True) as session:
            rows = (
                (
                    await session.execute(
                        select(BackgroundJobRow).where(BackgroundJobRow.idempotency_key == jobs[0].idempotency_key)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].id == result[0][0].id
            assert rows[0].status == "pending"
        return result

    first, second = await concurrently_requeue()

    assert first[0].id == second[0].id
    assert sorted((first[1], second[1])) == [False, True]
    claimed = await store.claim(owner="worker", lease_sec=30)
    assert claimed is not None
    assert await store.claim(owner="other", lease_sec=30) is None
    assert await store.complete(job_id=claimed.id, owner="worker", lease_id=claimed.lease_id or "")
    async with get_session(read_only=True) as session:
        assert (
            await session.execute(select(BackgroundJobRow).where(BackgroundJobRow.id == claimed.id))
        ).scalar_one_or_none() is None

    reactivated, competing = await concurrently_requeue()

    assert reactivated[0].id == competing[0].id
    assert reactivated[0].id != first[0].id
    assert sorted((reactivated[1], competing[1])) == [False, True]
