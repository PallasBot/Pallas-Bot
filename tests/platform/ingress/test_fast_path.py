from __future__ import annotations

import asyncio
import gc
import time
from queue import Queue
from threading import Event, Thread, get_ident
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
async def test_gate_queue_warning_threshold_is_not_read_for_each_call(
    isolated_gate_pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = 0

    def read_repo_setting(_key: str) -> str:
        nonlocal reads
        reads += 1
        return "1000"

    monkeypatch.setattr(fast_path, "repo_env_raw_value", read_repo_setting)

    await fast_path.run_gate_blocking(lambda: None)
    await fast_path.run_gate_blocking(lambda: None)

    assert reads == 0


@pytest.mark.asyncio
async def test_gate_queue_tombstone_does_not_emit_slow_execution_warning(
    isolated_gate_pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fast_path, "_GATE_ADMISSION_WAIT_SEC", 0.05)
    monkeypatch.setattr(fast_path, "gate_queue_warn_ms", lambda: 100.0)
    warnings: list[tuple] = []
    monkeypatch.setattr(fast_path, "log_rate_limited", lambda *args, **kwargs: warnings.append(args))

    started: Queue[None] = Queue()
    release = Event()
    executed: list[bool] = []

    def blocked_call() -> None:
        started.put(None)
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")

    blockers = [asyncio.create_task(fast_path.run_gate_blocking(blocked_call)) for _ in range(6)]
    queued = None
    release_thread = None
    try:
        await wait_until(lambda: started.qsize() == fast_path._GATE_WORKERS)
        queued = asyncio.create_task(fast_path.run_gate_blocking(lambda: executed.append(True)))
        await wait_until(lambda: len(fast_path._submitted_work) == 7)

        release_thread = Thread(target=lambda: (time.sleep(0.2), release.set()))
        release_thread.start()
        time.sleep(0.25)  # noqa: ASYNC251 - hold the loop so the worker can consume an expired tombstone.
        assert await queued is fast_path.GateNotStarted.WAIT_TIMEOUT
    finally:
        release.set()
        await asyncio.gather(*blockers, return_exceptions=True)
        if queued is not None:
            await asyncio.gather(queued, return_exceptions=True)
        if release_thread is not None:
            release_thread.join(timeout=1)

    assert executed == []
    assert not any(len(args) > 2 and args[2] == "gate_pool_queue" for args in warnings)


@pytest.mark.asyncio
async def test_saturated_gate_logs_active_task_types_and_ages(
    isolated_gate_pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fast_path, "_GATE_ADMISSION_WAIT_SEC", 0.05)
    warnings: list[tuple] = []
    monkeypatch.setattr(fast_path, "log_rate_limited", lambda *args, **kwargs: warnings.append(args))

    started: Queue[None] = Queue()
    release = Event()

    def blocked_call() -> None:
        started.put(None)
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")

    blockers = [asyncio.create_task(fast_path.run_gate_blocking(blocked_call)) for _ in range(6)]
    rejected = None
    executed: list[str] = []

    def should_not_run(secret: str) -> None:
        executed.append(secret)

    try:
        await wait_until(lambda: started.qsize() == fast_path._GATE_WORKERS)
        rejected = asyncio.create_task(fast_path.run_gate_blocking(should_not_run, "private-payload"))
        assert await rejected is fast_path.GateNotStarted.WAIT_TIMEOUT
    finally:
        release.set()
        await asyncio.gather(*blockers, return_exceptions=True)
        if rejected is not None:
            await asyncio.gather(rejected, return_exceptions=True)

    diagnostic = next(args for args in warnings if len(args) > 2 and args[2] == "gate_pool_not_started")
    assert "running tasks [{}]" in diagnostic[3]
    assert diagnostic[6] == fast_path._GATE_WORKERS
    assert diagnostic[7].count("blocked_call") == fast_path._GATE_WORKERS
    assert "ms" in diagnostic[7]
    assert "private-payload" not in repr(diagnostic)
    assert executed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancel", "exception"])
async def test_slow_queued_execution_logs_once_on_cancel_or_exception(
    isolated_gate_pool,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    monkeypatch.setattr(fast_path, "_GATE_ADMISSION_WAIT_SEC", 2.0)
    monkeypatch.setattr(fast_path, "gate_queue_warn_ms", lambda: 50.0)
    warnings: list[tuple] = []
    monkeypatch.setattr(fast_path, "log_rate_limited", lambda *args, **kwargs: warnings.append(args))

    blocker_started: Queue[None] = Queue()
    release_blockers = Event()
    release_queued_call = Event()
    queued_started = Event()

    def blocked_call() -> None:
        blocker_started.put(None)
        if not release_blockers.wait(3):
            raise TimeoutError("test gate worker was not released")

    def queued_call() -> None:
        queued_started.set()
        if outcome == "cancel":
            if not release_queued_call.wait(3):
                raise TimeoutError("test queued call was not released")
            return
        raise RuntimeError("injected queued call failure")

    blockers = [asyncio.create_task(fast_path.run_gate_blocking(blocked_call)) for _ in range(6)]
    queued = None
    try:
        await wait_until(lambda: blocker_started.qsize() == fast_path._GATE_WORKERS)
        queued = asyncio.create_task(fast_path.run_gate_blocking(queued_call))
        await wait_until(lambda: len(fast_path._submitted_work) == fast_path._GATE_WORKERS + 1)
        await asyncio.sleep(0.08)
        release_blockers.set()

        if outcome == "cancel":
            await wait_until(queued_started.is_set)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
        else:
            with pytest.raises(RuntimeError, match="injected queued call failure"):
                await queued
    finally:
        release_blockers.set()
        release_queued_call.set()
        await asyncio.gather(*blockers, return_exceptions=True)
        if queued is not None:
            await asyncio.gather(queued, return_exceptions=True)
        await wait_until(lambda: not fast_path._active_gate_calls)

    diagnostics = [
        args for args in warnings if len(args) > 4 and args[2] == "gate_pool_queue" and args[4] == "queued_call"
    ]
    assert len(diagnostics) == 1
    assert diagnostics[0][5] >= 50


@pytest.mark.asyncio
async def test_cancel_during_start_notification_logs_after_execution_completes(
    isolated_gate_pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fast_path, "_GATE_ADMISSION_WAIT_SEC", 2.0)
    monkeypatch.setattr(fast_path, "gate_queue_warn_ms", lambda: 50.0)
    main_thread_id = get_ident()
    warnings: list[tuple[tuple, int]] = []
    monkeypatch.setattr(
        fast_path,
        "log_rate_limited",
        lambda *args, **kwargs: warnings.append((args, get_ident())),
    )

    loop = asyncio.get_running_loop()
    call_soon_threadsafe = loop.call_soon_threadsafe
    notification_scheduled = Event()
    allow_worker_to_continue = Event()
    queued_started = Event()
    release_queued_call = Event()
    blocker_started: Queue[None] = Queue()
    release_blockers = Event()

    def blocked_call() -> None:
        blocker_started.put(None)
        if not release_blockers.wait(3):
            raise TimeoutError("test gate worker was not released")

    def queued_call() -> None:
        queued_started.set()
        if not release_queued_call.wait(3):
            raise TimeoutError("test queued call was not released")

    def pause_after_start_notification(callback, *args, **kwargs):
        handle = call_soon_threadsafe(callback, *args, **kwargs)
        owner = getattr(callback, "__self__", None)
        if isinstance(owner, fast_path._GateCall) and owner.func is queued_call:
            notification_scheduled.set()
            if not allow_worker_to_continue.wait(3):
                raise TimeoutError("test gate worker was not released after notification")
        return handle

    monkeypatch.setattr(loop, "call_soon_threadsafe", pause_after_start_notification)
    blockers = [asyncio.create_task(fast_path.run_gate_blocking(blocked_call)) for _ in range(6)]
    queued = None
    target_call = None
    try:
        await wait_until(lambda: blocker_started.qsize() == fast_path._GATE_WORKERS)
        queued = asyncio.create_task(fast_path.run_gate_blocking(queued_call))
        await wait_until(lambda: len(fast_path._submitted_work) == fast_path._GATE_WORKERS + 1)
        target_call = next(call for call in fast_path._submitted_work if call.func is queued_call)
        await asyncio.sleep(0.08)
        release_blockers.set()

        assert await asyncio.wait_for(asyncio.to_thread(notification_scheduled.wait), timeout=1)
        await wait_until(lambda: target_call.started_future.done())
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert not any(args[2] == "gate_pool_queue" and args[4] == "queued_call" for args, _ in warnings)

        allow_worker_to_continue.set()
        await wait_until(queued_started.is_set)
        release_queued_call.set()
        await wait_until(lambda: target_call.execution_details()[1] is not None)
        await wait_until(lambda: any(args[2] == "gate_pool_queue" for args, _ in warnings))
    finally:
        release_blockers.set()
        allow_worker_to_continue.set()
        release_queued_call.set()
        await asyncio.gather(*blockers, return_exceptions=True)
        if queued is not None:
            await asyncio.gather(queued, return_exceptions=True)
        await wait_until(lambda: not fast_path._active_gate_calls)

    diagnostics = [
        (args, thread_id)
        for args, thread_id in warnings
        if len(args) > 4 and args[2] == "gate_pool_queue" and args[4] == "queued_call"
    ]
    assert len(diagnostics) == 1
    assert diagnostics[0][0][5] >= 50
    assert diagnostics[0][1] == main_thread_id


@pytest.mark.asyncio
async def test_cancelled_queued_gate_tombstone_does_not_emit_execution_warning(
    isolated_gate_pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fast_path, "_GATE_ADMISSION_WAIT_SEC", 2.0)
    monkeypatch.setattr(fast_path, "gate_queue_warn_ms", lambda: 50.0)
    warnings: list[tuple] = []
    monkeypatch.setattr(fast_path, "log_rate_limited", lambda *args, **kwargs: warnings.append(args))

    blocker_started: Queue[None] = Queue()
    release = Event()
    executed: list[bool] = []

    def blocked_call() -> None:
        blocker_started.put(None)
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")

    def tombstone_call() -> None:
        executed.append(True)

    blockers = [asyncio.create_task(fast_path.run_gate_blocking(blocked_call)) for _ in range(6)]
    queued = None
    try:
        await wait_until(lambda: blocker_started.qsize() == fast_path._GATE_WORKERS)
        queued = asyncio.create_task(fast_path.run_gate_blocking(tombstone_call))
        await wait_until(lambda: len(fast_path._submitted_work) == fast_path._GATE_WORKERS + 1)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
    finally:
        release.set()
        await asyncio.gather(*blockers, return_exceptions=True)
        if queued is not None:
            await asyncio.gather(queued, return_exceptions=True)
        await wait_until(lambda: not fast_path._submitted_work)

    assert executed == []
    assert not any(len(args) > 4 and args[2] == "gate_pool_queue" and args[4] == "tombstone_call" for args in warnings)


@pytest.mark.asyncio
async def test_worker_config_refresh_picks_up_shared_settings_change(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.foundation.config import repo_settings, webui_export_toml

    original = fast_path.gate_queue_warn_ms()
    webui_path = tmp_path / "webui.json"
    monkeypatch.setattr(repo_settings, "repo_webui_settings_path", lambda: webui_path)
    monkeypatch.setattr(webui_export_toml, "export_webui_inspection_toml", lambda *_args: None)
    monkeypatch.delenv("PALLAS_GATE_QUEUE_WARN_MS", raising=False)
    repo_settings.clear_merged_repo_settings_cache()
    repo_settings.upsert_repo_settings_items({"PALLAS_GATE_QUEUE_WARN_MS": "1000"})
    worker_snapshot = repo_settings.merged_repo_settings_upper()
    worker_revision = repo_settings._merged_settings_cache_rev
    monkeypatch.setattr(fast_path, "_GATE_CONFIG_REFRESH_INTERVAL_SEC", 0.01, raising=False)
    fast_path.set_gate_queue_warn_ms(1000.0)

    fast_path.start_gate_queue_config_refresh_loop()
    try:
        await asyncio.sleep(0.03)
        repo_settings.upsert_repo_settings_items({"PALLAS_GATE_QUEUE_WARN_MS": "2300.0"})
        repo_settings._merged_settings_cache = worker_snapshot
        repo_settings._merged_settings_cache_rev = worker_revision
        fast_path.set_gate_queue_warn_ms(1000.0)
        await wait_until(lambda: fast_path.gate_queue_warn_ms() == 2300.0)
    finally:
        await fast_path.stop_gate_queue_config_refresh_loop()
        fast_path.set_gate_queue_warn_ms(original)
        repo_settings.clear_merged_repo_settings_cache()


@pytest.mark.asyncio
async def test_active_gate_diagnostics_clean_up_after_cancel_and_exception(isolated_gate_pool) -> None:
    started = Event()
    release = Event()

    def blocked_call() -> None:
        started.set()
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")

    task = asyncio.create_task(fast_path.run_gate_blocking(blocked_call))
    try:
        await wait_until(started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(fast_path._active_gate_calls) == 1
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)

    await wait_until(lambda: not fast_path._active_gate_calls)

    def fail_after_start() -> None:
        raise RuntimeError("injected gate task failure")

    with pytest.raises(RuntimeError, match="injected gate task failure"):
        await fast_path.run_gate_blocking(fail_after_start)
    assert not fast_path._active_gate_calls


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
