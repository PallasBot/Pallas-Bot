from __future__ import annotations

import asyncio
import gc
from queue import Queue
from threading import Event, Thread
from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import IgnoredException

from pallas.core.platform.ingress import fast_path
from pallas.core.platform.ingress.fast_path import ingress_once_claim_safe_before_host_gates
from pallas.core.platform.shard.registry import config as shard_cfg


async def wait_until(predicate) -> None:
    async with asyncio.timeout(1):
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_gate_admission_bounds_executor_queue_and_waiters(
    isolated_gate_pool,
) -> None:
    from pallas.core.platform.ingress.fast_path import GateNotStarted, run_gate_blocking

    assert fast_path._GATE_WORKERS == 6
    assert fast_path._GATE_QUEUE_CAPACITY == 12
    assert fast_path._GATE_MAX_WAITERS == 64
    assert fast_path._GATE_ADMISSION_WAIT_SEC == 0.25

    started: Queue[int] = Queue()
    release = Event()

    def blocked_call(value: int) -> int:
        started.put(value)
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")
        return value

    submitted = [asyncio.create_task(run_gate_blocking(blocked_call, i)) for i in range(18)]
    waiters = []
    try:
        await wait_until(lambda: started.qsize() == fast_path._GATE_WORKERS)
        await wait_until(lambda: len(fast_path._submitted_work) == 18)

        waiters = [asyncio.create_task(run_gate_blocking(blocked_call, 100 + i)) for i in range(64)]
        await asyncio.sleep(0)
        assert fast_path._gate_waiters == fast_path._GATE_MAX_WAITERS
        assert await run_gate_blocking(blocked_call, 999) is GateNotStarted.SATURATED
        assert 999 not in list(started.queue)

        release.set()
        results = await asyncio.gather(*submitted, *waiters)
        assert results[:18] == list(range(18))
    finally:
        release.set()
        await asyncio.gather(*submitted, *waiters, return_exceptions=True)


@pytest.mark.asyncio
async def test_gate_queue_wait_timeout_returns_not_started(isolated_gate_pool) -> None:
    from pallas.core.platform.ingress.fast_path import GateNotStarted, run_gate_blocking

    started: Queue[int] = Queue()
    release = Event()

    def blocked_call(value: int) -> int:
        started.put(value)
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")
        return value

    submitted = [asyncio.create_task(run_gate_blocking(blocked_call, i)) for i in range(18)]
    try:
        await wait_until(lambda: started.qsize() == fast_path._GATE_WORKERS)
        await wait_until(lambda: len(fast_path._submitted_work) == 18)

        started_at = asyncio.get_running_loop().time()
        result = await run_gate_blocking(blocked_call, 999)

        assert result is GateNotStarted.WAIT_TIMEOUT
        assert 0.2 <= asyncio.get_running_loop().time() - started_at < 1.0
        assert 999 not in list(started.queue)
    finally:
        release.set()
        await asyncio.gather(*submitted, return_exceptions=True)


@pytest.mark.asyncio
async def test_executor_thread_start_failure_tombstones_submission_and_poisons_pool(
    isolated_gate_pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.ingress.fast_path import GateNotStarted, run_gate_blocking, shutdown_gate_executor

    loop = asyncio.get_running_loop()
    loop_errors: list[dict] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    worker_started = Event()
    release_worker = Event()
    executed: list[int] = []

    def blocked_worker() -> None:
        worker_started.set()
        if not release_worker.wait(3):
            raise TimeoutError("test gate worker was not released")

    def should_not_run(value: int) -> int:
        executed.append(value)
        return value

    blocker = asyncio.create_task(run_gate_blocking(blocked_worker))
    executor = fast_path._executor
    results = []
    queue_size = -1
    original_start = Thread.start

    def fail_start(_thread: Thread) -> None:
        raise RuntimeError("injected worker startup failure")

    try:
        await wait_until(worker_started.is_set)
        executor = fast_path._executor
        assert executor is not None
        monkeypatch.setattr(Thread, "start", fail_start)
        results = [await run_gate_blocking(should_not_run, i) for i in range(20)]
        queue_size = executor._work_queue.qsize()
    finally:
        monkeypatch.setattr(Thread, "start", original_start)
        release_worker.set()
        shutdown_gate_executor()
        await asyncio.gather(blocker, return_exceptions=True)
        if executor is not None:
            await asyncio.gather(*(asyncio.to_thread(thread.join, 3) for thread in executor._threads))
        await wait_until(lambda: fast_path._gate_slots._value == fast_path._GATE_QUEUE_CAPACITY)
        loop.set_exception_handler(old_handler)

    assert len(results) == 20
    assert results == [GateNotStarted.SHUTDOWN] * 20
    assert queue_size <= fast_path._GATE_QUEUE_CAPACITY
    assert executed == []
    assert loop_errors == []


@pytest.mark.asyncio
async def test_executor_start_failure_cannot_run_queued_call_before_rejection(
    isolated_gate_pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.ingress.fast_path import GateNotStarted, run_gate_blocking, shutdown_gate_executor

    worker_started = Event()
    release_worker = Event()
    executed: list[int] = []
    extra_workers: list[Thread] = []
    original_start = Thread.start
    loop = asyncio.get_running_loop()
    loop_errors: list[dict] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))

    def blocked_worker() -> None:
        worker_started.set()
        if not release_worker.wait(3):
            raise TimeoutError("test gate worker was not released")

    def should_not_run(value: int) -> int:
        executed.append(value)
        return value

    blocker = asyncio.create_task(run_gate_blocking(blocked_worker))
    executor = None
    try:
        await wait_until(worker_started.is_set)
        executor = fast_path._executor
        assert executor is not None

        def start_then_fail(thread: Thread) -> None:
            original_start(thread)
            extra_workers.append(thread)
            raise RuntimeError("injected post-start failure")

        monkeypatch.setattr(Thread, "start", start_then_fail)
        result = await run_gate_blocking(should_not_run, 1)
        assert result is GateNotStarted.SHUTDOWN
    finally:
        monkeypatch.setattr(Thread, "start", original_start)
        release_worker.set()
        shutdown_gate_executor()
        await asyncio.gather(blocker, return_exceptions=True)
        threads = set(extra_workers)
        if executor is not None:
            threads.update(executor._threads)
        await asyncio.gather(*(asyncio.to_thread(thread.join, 3) for thread in threads))
        await wait_until(lambda: fast_path._gate_slots._value == fast_path._GATE_QUEUE_CAPACITY)
        loop.set_exception_handler(old_handler)

    assert executed == []
    assert fast_path._gate_slots._value == fast_path._GATE_QUEUE_CAPACITY
    assert loop_errors == []


@pytest.mark.asyncio
async def test_gate_deadline_covers_executor_queue_and_keeps_tombstone_capacity(
    isolated_gate_pool,
) -> None:
    from pallas.core.platform.ingress.fast_path import GateNotStarted, run_gate_blocking

    started: Queue[int] = Queue()
    release = Event()

    def blocked_call(value: int) -> int:
        started.put(value)
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")
        return value

    running = [asyncio.create_task(run_gate_blocking(blocked_call, i)) for i in range(6)]
    queued = []
    try:
        await wait_until(lambda: started.qsize() == fast_path._GATE_WORKERS)
        queued = [asyncio.create_task(run_gate_blocking(blocked_call, i)) for i in range(6, 18)]
        await wait_until(lambda: len(fast_path._submitted_work) == 18)
        await asyncio.sleep(0.45)

        assert all(task.done() for task in queued)
        assert all(not task.done() for task in running)
        assert await asyncio.gather(*queued) == [GateNotStarted.WAIT_TIMEOUT] * 12
        assert fast_path._gate_slots._value == 0
        assert len(fast_path._submitted_work) == 18
        assert set(started.queue).isdisjoint(range(6, 18))
    finally:
        release.set()
        await asyncio.gather(*running, *queued, return_exceptions=True)

    await wait_until(lambda: not fast_path._submitted_work)
    assert set(started.queue).isdisjoint(range(6, 18))


@pytest.mark.asyncio
async def test_gate_rejects_calls_from_a_different_event_loop(
    isolated_gate_pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.ingress.fast_path import GateNotStarted, run_gate_blocking

    monkeypatch.setattr(fast_path, "_GATE_ADMISSION_WAIT_SEC", 2.0)
    loop_ready = Event()
    first_loop: list[asyncio.AbstractEventLoop] = []
    thread_errors: list[BaseException] = []

    async def hold_all_slots() -> None:
        assert await run_gate_blocking(lambda: None) is None
        await wait_until(lambda: fast_path._gate_slots._value == fast_path._GATE_QUEUE_CAPACITY)
        for _ in range(fast_path._GATE_QUEUE_CAPACITY):
            await fast_path._gate_slots.acquire()
        first_loop.append(asyncio.get_running_loop())
        waiter = asyncio.create_task(fast_path._gate_slots.acquire())
        await asyncio.sleep(0)
        loop_ready.set()
        await waiter

    def run_first_loop() -> None:
        try:
            asyncio.run(hold_all_slots())
        except BaseException as exc:
            thread_errors.append(exc)
            loop_ready.set()

    thread = Thread(target=run_first_loop)
    thread.start()
    try:
        assert await asyncio.to_thread(loop_ready.wait, 2)
        assert not thread_errors

        def run_second_loop():
            async def call_gate():
                return await run_gate_blocking(lambda: "must not run")

            return asyncio.run(call_gate())

        result = await asyncio.to_thread(run_second_loop)
        assert result is GateNotStarted.LOOP_MISMATCH
    finally:
        if first_loop:
            first_loop[0].call_soon_threadsafe(fast_path._gate_slots.release)
        thread.join(timeout=2)
    assert not thread.is_alive()


@pytest.mark.asyncio
async def test_gate_cancellation_skips_queued_work_and_holds_running_capacity(
    isolated_gate_pool,
) -> None:
    from pallas.core.platform.ingress.fast_path import run_gate_blocking

    started: Queue[int] = Queue()
    completed: Queue[int] = Queue()
    release = Event()

    def blocked_call(value: int) -> int:
        started.put(value)
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")
        completed.put(value)
        return value

    submitted = [asyncio.create_task(run_gate_blocking(blocked_call, i)) for i in range(18)]
    try:
        await wait_until(lambda: started.qsize() == fast_path._GATE_WORKERS)
        await wait_until(lambda: len(fast_path._submitted_work) == 18)

        active_id = started.get_nowait()
        submitted[active_id].cancel()
        with pytest.raises(asyncio.CancelledError):
            await submitted[active_id]

        queued_id = 17
        submitted[queued_id].cancel()
        with pytest.raises(asyncio.CancelledError):
            await submitted[queued_id]

        assert fast_path._gate_slots._value == 0
        assert len(fast_path._submitted_work) == 18

        release.set()
        await asyncio.gather(*(task for i, task in enumerate(submitted) if i not in {active_id, queued_id}))
        await wait_until(lambda: completed.qsize() == 17)
        assert queued_id not in list(completed.queue)
        assert await run_gate_blocking(lambda: "capacity released") == "capacity released"
    finally:
        release.set()
        await asyncio.gather(*submitted, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_running_gate_retrieves_late_worker_exception(isolated_gate_pool) -> None:
    from pallas.core.platform.ingress.fast_path import run_gate_blocking

    loop = asyncio.get_running_loop()
    contexts: list[dict] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: contexts.append(context))
    started = Event()
    release = Event()

    def fail_after_release() -> None:
        started.set()
        if not release.wait(2):
            raise TimeoutError("test gate worker was not released")
        raise RuntimeError("late worker failure")

    task = asyncio.create_task(run_gate_blocking(fail_after_release))
    try:
        await wait_until(started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await wait_until(lambda: not fast_path._submitted_work)
        gc.collect()
        await asyncio.sleep(0)

        assert not any("Future exception was never retrieved" in context.get("message", "") for context in contexts)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        loop.set_exception_handler(old_handler)


@pytest.mark.asyncio
async def test_gate_shutdown_skips_queued_work_and_never_recreates_pool(isolated_gate_pool) -> None:
    from pallas.core.platform.ingress.fast_path import GateNotStarted, run_gate_blocking, shutdown_gate_executor

    started: Queue[int] = Queue()
    release = Event()
    executed: list[int] = []

    def blocked_call(value: int) -> int:
        started.put(value)
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")
        executed.append(value)
        return value

    submitted = [asyncio.create_task(run_gate_blocking(blocked_call, i)) for i in range(18)]
    try:
        await wait_until(lambda: started.qsize() == fast_path._GATE_WORKERS)
        await wait_until(lambda: len(fast_path._submitted_work) == 18)

        shutdown_gate_executor()
        assert await run_gate_blocking(blocked_call, 999) is GateNotStarted.SHUTDOWN
        assert fast_path._executor is None

        release.set()
        results = await asyncio.gather(*submitted)
        assert results[:6] == list(range(6))
        assert results[6:] == [GateNotStarted.SHUTDOWN] * 12
        assert set(executed) == set(range(6))
    finally:
        release.set()
        await asyncio.gather(*submitted, return_exceptions=True)


def test_ingress_once_claim_safe_when_no_host_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.needs_group_host_bot_gate",
        lambda: False,
    )
    assert ingress_once_claim_safe_before_host_gates(1, "hello", at_fleet_bot=False) is True


def test_ingress_once_claim_unsafe_when_spy_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.needs_group_host_bot_gate",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.loaded_hosted_activity_specs",
        lambda: (),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.read_owned_gate_bot_id_sync",
        lambda _plugin, _gid: None,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.hosted_activity_live",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.spec_matches_in_room_command",
        lambda _spec, _plain: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.spec_matches_speak_traffic",
        lambda *_args, **_kwargs: False,
    )
    from types import SimpleNamespace

    spec = SimpleNamespace(
        activity_namespace="spy",
        plugin_key="who_is_spy",
        always_pass_prefixes=(),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.loaded_hosted_activity_specs",
        lambda: (spec,),
    )
    assert ingress_once_claim_safe_before_host_gates(1, "牛牛卧底", at_fleet_bot=False) is False


@pytest.mark.asyncio
async def test_unified_ingress_early_once_claim_before_host_checks(
    monkeypatch: pytest.MonkeyPatch,
    isolated_gate_pool,
) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.ingress_once_claim_safe_before_host_gates",
        lambda *_args, **_kwargs: True,
    )
    hosted = MagicMock(return_value=True)
    dream = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.hosted_activity_ingress_passes", hosted)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.dream_session_ingress_passes", dream)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.claim_federate_group_message_ingress",
        AsyncMock(return_value=True),
    )
    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    class FakeBot:
        def __init__(self, self_id: int) -> None:
            self.self_id = str(self_id)

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("热路径"),
        raw_message="热路径",
    )

    await ingress_group_message_gate(FakeBot(111), event)
    hosted.assert_called()
    dream.assert_called()

    hosted.reset_mock()
    dream.reset_mock()
    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(222), event)
    hosted.assert_not_called()
    dream.assert_not_called()


@pytest.mark.asyncio
async def test_hosted_activity_owner_precedes_peer_alias_yield(
    monkeypatch: pytest.MonkeyPatch,
    isolated_gate_pool,
) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.shard_ctx.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.ingress_once_claim_safe_before_host_gates",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_process_federate_group_on_current_deployment",
        lambda _gid, **_kwargs: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.alias_route.should_yield_ingress_for_peer_alias",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.hosted_activity_claim_is_hosted",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.hosted_activity_ingress_passes",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.dream_session_ingress_passes", AsyncMock(return_value=True))
    monkeypatch.setattr("pallas.core.platform.ingress.gate.run_ingress_message_claim", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.claim_federate_group_message_ingress",
        AsyncMock(return_value=True),
    )

    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    class FakeBot:
        self_id = "111"

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=733291779,
        message_id=1,
        message=Message("帕拉斯"),
        raw_message="帕拉斯",
    )

    await ingress_group_message_gate(FakeBot(), event)
