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

    first = asyncio.create_task(pool.submit(("10001", 1), lambda: work(1)))
    second = asyncio.create_task(pool.submit(("10001", 1), lambda: work(2)))
    await asyncio.wait_for(start_gate.wait(), timeout=5)
    assert sorted(started) == [1, 2]

    third = asyncio.create_task(pool.submit(("10001", 1), lambda: work(3)))
    await asyncio.sleep(0)
    assert third.done() is False
    assert started == [1, 2]

    release.set()
    await asyncio.gather(first, second, third)
    assert started == [1, 2, 3]
    await pool.stop()


@pytest.mark.asyncio
async def test_pool_drops_work_when_queue_full_and_droppable() -> None:
    pool = PassiveWorkPool("nth", max_concurrency=1, queue_max=1, droppable=True)
    started = asyncio.Event()
    release = asyncio.Event()

    async def work() -> None:
        started.set()
        await release.wait()

    first = asyncio.create_task(pool.submit(("10001", 1), work))
    await started.wait()
    second = asyncio.create_task(pool.submit(("10001", 1), lambda: asyncio.sleep(0)))
    await asyncio.sleep(0)
    assert second.done() is False

    third = asyncio.create_task(pool.submit(("10001", 1), lambda: asyncio.sleep(0)))
    await asyncio.sleep(0)
    assert third.done() is True

    release.set()
    await first
    await pool.stop()
    assert pool.snapshot()["dropped"] == 1
