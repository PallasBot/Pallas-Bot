from __future__ import annotations

import asyncio

import pytest

from pallas.core.platform.ingress.conversation_scheduler import ConversationScheduler


@pytest.mark.asyncio
async def test_same_conversation_runs_in_fifo_order() -> None:
    scheduler = ConversationScheduler(concurrency=2, max_pending=8)
    seen: list[int] = []

    async def record(value: int) -> None:
        seen.append(value)

    await asyncio.gather(*(scheduler.submit(("10001", 1), lambda value=value: record(value)) for value in (1, 2, 3)))

    assert seen == [1, 2, 3]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_hot_conversation_does_not_starve_ready_conversation() -> None:
    scheduler = ConversationScheduler(concurrency=1, max_pending=8)
    started = asyncio.Event()
    release_first = asyncio.Event()
    seen: list[str] = []

    async def first() -> None:
        seen.append("a1")
        started.set()
        await release_first.wait()

    async def record(value: str) -> None:
        seen.append(value)

    a1 = asyncio.create_task(scheduler.submit(("10001", 1), first))
    await started.wait()
    a2 = asyncio.create_task(scheduler.submit(("10001", 1), lambda: record("a2")))
    b1 = asyncio.create_task(scheduler.submit(("10001", 2), lambda: record("b1")))
    await scheduler.wait_for_pending_at_least(3)
    release_first.set()

    await asyncio.gather(a1, a2, b1)

    assert seen == ["a1", "b1", "a2"]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_submit_waits_for_capacity_without_dropping_work() -> None:
    scheduler = ConversationScheduler(concurrency=1, max_pending=1)
    started = asyncio.Event()
    release_first = asyncio.Event()
    seen: list[str] = []

    async def first() -> None:
        seen.append("first")
        started.set()
        await release_first.wait()

    async def second() -> None:
        seen.append("second")

    first_task = asyncio.create_task(scheduler.submit(("10001", 1), first))
    await started.wait()
    second_task = asyncio.create_task(scheduler.submit(("10001", 2), second))
    await asyncio.sleep(0)

    assert second_task.done() is False
    assert scheduler.snapshot()["pending"] == 1

    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert seen == ["first", "second"]
    await scheduler.stop()
