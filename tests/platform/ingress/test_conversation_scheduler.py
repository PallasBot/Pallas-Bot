from __future__ import annotations

import asyncio

import pytest

from pallas.core.platform.ingress.conversation_scheduler import ConversationScheduler


def test_per_key_pending_is_clamped_to_positive_value() -> None:
    scheduler = ConversationScheduler(concurrency=1, max_pending=4, per_key_pending=0)

    assert scheduler.snapshot()["per_key_pending_limit"] == 1


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
async def test_hot_conversation_cannot_fill_all_pending_capacity() -> None:
    scheduler = ConversationScheduler(concurrency=1, max_pending=4, per_key_pending=2)
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
    await scheduler.wait_for_pending_at_least(2)
    a3 = asyncio.create_task(scheduler.submit(("10001", 1), lambda: record("a3")))
    await asyncio.sleep(0)

    assert a3.done() is False

    b1 = asyncio.create_task(scheduler.submit(("10001", 2), lambda: record("b1")))
    await scheduler.wait_for_pending_at_least(3)
    release_first.set()

    await asyncio.gather(a1, a2, a3, b1)

    assert seen == ["a1", "b1", "a2", "a3"]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_stop_releases_pending_capacity_for_queued_conversations() -> None:
    scheduler = ConversationScheduler(concurrency=1, max_pending=4, per_key_pending=2)
    started = asyncio.Event()
    release_first = asyncio.Event()

    async def first() -> None:
        started.set()
        await release_first.wait()

    first_task = asyncio.create_task(scheduler.submit(("10001", 1), first))
    await started.wait()
    queued_task = asyncio.create_task(scheduler.submit(("10001", 2), lambda: asyncio.sleep(0)))
    await scheduler.wait_for_pending_at_least(2)

    await scheduler.stop()

    assert scheduler.snapshot()["pending"] == 0
    assert scheduler.snapshot()["active_keys"] == 0
    assert queued_task.cancelled()
    assert first_task.cancelled()


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


@pytest.mark.asyncio
async def test_reservation_occupies_capacity_before_handler_submission() -> None:
    scheduler = ConversationScheduler(concurrency=1, max_pending=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def work() -> None:
        started.set()
        await release.wait()

    reservation = await scheduler.reserve(("10001", 1))
    handler = asyncio.create_task(scheduler.submit(("10001", 1), work, reservation=reservation))
    await started.wait()

    next_reservation = asyncio.create_task(scheduler.reserve(("10001", 2)))
    await asyncio.sleep(0)

    assert next_reservation.done() is False
    assert scheduler.snapshot()["pending"] == 1

    release.set()
    await handler
    next_reservation_value = await next_reservation
    await next_reservation_value.release()
    assert scheduler.snapshot()["pending"] == 0
    await scheduler.stop()
