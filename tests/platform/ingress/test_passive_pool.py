from __future__ import annotations

import asyncio

import pytest

from pallas.core.platform.ingress.passive_pool import PassiveWorkPool


@pytest.mark.asyncio
async def test_pool_enforces_concurrency_and_keeps_undroppable_work() -> None:
    pool = PassiveWorkPool("repeater", max_concurrency=2, queue_max=4, droppable=False)
    started: list[int] = []
    release = asyncio.Event()
    start_gate = asyncio.Event()

    async def work(value: int) -> None:
        started.append(value)
        if len(started) == 2:
            start_gate.set()
        await release.wait()

    first = asyncio.create_task(pool.submit(lambda: work(1)))
    second = asyncio.create_task(pool.submit(lambda: work(2)))
    await asyncio.wait_for(start_gate.wait(), timeout=5)
    assert sorted(started) == [1, 2]

    third = asyncio.create_task(pool.submit(lambda: work(3)))
    await asyncio.sleep(0)
    assert third.done() is False
    assert started == [1, 2]

    release.set()
    await asyncio.gather(first, second, third)
    assert started == [1, 2, 3]
    await pool.stop()


@pytest.mark.asyncio
async def test_pool_drops_work_when_queue_full_and_droppable() -> None:
    pool = PassiveWorkPool("extra", max_concurrency=1, queue_max=1, droppable=True)
    started = asyncio.Event()
    release = asyncio.Event()

    async def work() -> None:
        started.set()
        await release.wait()

    first = asyncio.create_task(pool.submit(work))
    await started.wait()
    second = asyncio.create_task(pool.submit(lambda: asyncio.sleep(0)))
    await asyncio.sleep(0)
    assert second.done() is False

    third = asyncio.create_task(pool.submit(lambda: asyncio.sleep(0)))
    await asyncio.sleep(0)
    assert third.done() is True

    release.set()
    await first
    await pool.stop()
    assert pool.snapshot()["dropped"] == 1


@pytest.mark.asyncio
async def test_pool_reports_running_work_duration_and_oldest_age() -> None:
    pool = PassiveWorkPool("repeater", max_concurrency=1, queue_max=1, droppable=False)
    started = asyncio.Event()
    release = asyncio.Event()

    async def work() -> None:
        started.set()
        await release.wait()

    submit = asyncio.create_task(pool.submit(work))
    await started.wait()
    await asyncio.sleep(0.01)

    snapshot = pool.snapshot()

    assert snapshot["active"] == 1
    assert snapshot["active_oldest_ms"] >= 10
    assert snapshot["run_ms_p95"] is None

    release.set()
    await submit
    await asyncio.sleep(0)
    snapshot = pool.snapshot()
    assert snapshot["run_ms_p95"] >= 10
    await pool.stop()
