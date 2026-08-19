from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

ConversationKey = tuple[str, int]
Work = Callable[[], Awaitable[None]]


class PassiveWorkPool:
    def __init__(self, name: str, *, max_concurrency: int, queue_max: int, droppable: bool) -> None:
        self.name = name
        self.max_concurrency = max(1, int(max_concurrency))
        self.queue_max = max(1, int(queue_max))
        self.droppable = droppable
        self._pending = 0
        self._pending_peak = 0
        self._dropped = 0
        self._active = 0
        self._wait_samples_ms: deque[float] = deque(maxlen=256)
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = False
        self._sem = asyncio.Semaphore(self.max_concurrency)
        self._changed = asyncio.Event()

    async def submit(self, key: ConversationKey, work: Work) -> None:
        if self._stopping:
            return
        queued_at = time.monotonic()
        self._pending += 1
        self._pending_peak = max(self._pending_peak, self._pending)
        self._changed.set()
        try:
            if self.droppable and self._pending > self.queue_max:
                self._dropped += 1
                return
            await self._sem.acquire()
            self._pending = max(0, self._pending - 1)
            self._active += 1
            self._wait_samples_ms.append((time.monotonic() - queued_at) * 1000.0)
            task = asyncio.create_task(self._run(work), name=f"passive_{self.name}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except asyncio.CancelledError:
            raise

    async def _run(self, work: Work) -> None:
        try:
            await work()
        finally:
            self._active = max(0, self._active - 1)
            self._changed.set()
            self._sem.release()

    def snapshot(self) -> dict[str, int | float]:
        ordered = sorted(self._wait_samples_ms)
        wait_p95 = None
        if ordered:
            index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95)))
            wait_p95 = round(ordered[index], 2)
        return {
            "name": self.name,
            "pending": self._pending,
            "pending_peak": self._pending_peak,
            "active": self._active,
            "dropped": self._dropped,
            "wait_ms_p95": wait_p95,
        }

    async def wait_pending_at_least(self, count: int) -> None:
        while self._pending < count and not self._stopping:
            self._changed.clear()
            if self._pending >= count:
                break
            await asyncio.wait_for(self._changed.wait(), timeout=5)

    async def stop(self) -> None:
        self._stopping = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
