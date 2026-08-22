from __future__ import annotations

import asyncio
import threading
import time

from pallas.core.foundation import asgi_runner as mod


def test_process_shutdown_callback_runs_before_forced_exit() -> None:
    calls: list[str] = []
    mod.register_process_shutdown_callback(lambda: calls.append("cleanup"))
    try:
        mod.run_process_shutdown_callback()
    finally:
        mod.clear_process_shutdown_callback()

    assert calls == ["cleanup"]


def test_shutdown_loop_cancels_pending_tasks_and_times_out_executor() -> None:
    gate = threading.Event()

    async def blocked() -> None:
        await asyncio.to_thread(gate.wait, 30)

    async def spawn() -> asyncio.Task:
        task = asyncio.create_task(blocked())
        await asyncio.sleep(0.05)
        assert not task.done()
        return task

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        task = loop.run_until_complete(spawn())
        start = time.monotonic()
        timed_out = mod._shutdown_loop(loop, executor_timeout=0.2)
        elapsed = time.monotonic() - start
        assert timed_out is True
        assert task.cancelled() is True
        assert elapsed < 5.0
    finally:
        gate.set()
        asyncio.set_event_loop(None)
        loop.close()


def test_shutdown_loop_returns_false_when_executor_drains() -> None:
    async def quick() -> None:
        await asyncio.to_thread(time.sleep, 0.05)

    async def spawn() -> asyncio.Task:
        task = asyncio.create_task(quick())
        await asyncio.sleep(0.05)
        return task

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        task = loop.run_until_complete(spawn())
        timed_out = mod._shutdown_loop(loop, executor_timeout=5.0)
        assert timed_out is False
        assert task.done() is True
    finally:
        asyncio.set_event_loop(None)
        loop.close()
