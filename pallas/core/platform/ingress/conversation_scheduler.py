from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from pallas.core.platform.ingress.dispatch_runtime_config import get_ingress_dispatch_runtime_config

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event

ConversationKey = tuple[str, int]
Work = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class ConversationWork:
    work: Work
    future: asyncio.Future[None]
    queued_at: float


@dataclass(slots=True)
class ConversationCapacityReservation:
    scheduler: ConversationScheduler
    key: ConversationKey
    _claimed: bool = False
    _queued: bool = False
    _released: bool = False

    async def release(self) -> None:
        await self.scheduler.release_reservation(self)


class ConversationScheduler:
    def __init__(self, *, concurrency: int, max_pending: int, per_key_pending: int | None = None) -> None:
        self.concurrency = max(1, int(concurrency))
        self.max_pending = max(1, int(max_pending))
        self.per_key_pending = max(1, int(per_key_pending if per_key_pending is not None else self.max_pending))
        self._queues: dict[ConversationKey, deque[ConversationWork]] = {}
        self._ready: deque[ConversationKey] = deque()
        self._ready_keys: set[ConversationKey] = set()
        self._running_keys: set[ConversationKey] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._pending_count = 0
        self._pending_by_key: dict[ConversationKey, int] = {}
        self._scheduled_by_key: dict[ConversationKey, int] = {}
        self._pending_peak = 0
        self._ready_peak = 0
        self._active_peak = 0
        self._backpressure_waits = 0
        self._per_key_backpressure_waits = 0
        self._wait_samples_ms: deque[float] = deque(maxlen=256)
        self._stopping = False
        self._condition = asyncio.Condition()

    async def submit(
        self,
        key: ConversationKey,
        work: Work,
        *,
        reservation: ConversationCapacityReservation | None = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        item = ConversationWork(work=work, future=future, queued_at=time.monotonic())
        async with self._condition:
            reserved = reservation is not None and reservation.scheduler is self
            if reserved:
                if reservation.key != key or reservation._claimed or reservation._released:
                    raise RuntimeError("conversation capacity reservation is no longer available")
                reservation._claimed = True
                while not self._stopping and self._scheduled_by_key.get(key, 0) >= self.per_key_pending:
                    self._per_key_backpressure_waits += 1
                    await self._condition.wait()
            else:
                while not self._stopping and (
                    self._pending_count >= self.max_pending
                    or self._scheduled_by_key.get(key, 0) >= self.per_key_pending
                ):
                    self._backpressure_waits += 1
                    if self._scheduled_by_key.get(key, 0) >= self.per_key_pending:
                        self._per_key_backpressure_waits += 1
                    await self._condition.wait()
            if self._stopping:
                if reserved:
                    reservation._claimed = False
                    self._release_reservation_locked(reservation)
                raise RuntimeError("conversation scheduler is stopping")
            if not reserved:
                self._pending_count += 1
                self._pending_by_key[key] = self._pending_by_key.get(key, 0) + 1
            self._queues.setdefault(key, deque()).append(item)
            self._scheduled_by_key[key] = self._scheduled_by_key.get(key, 0) + 1
            if reserved:
                reservation._queued = True
            self._queue_ready_key_locked(key)
            self._record_peaks_locked()
            self._start_ready_locked()
            self._condition.notify_all()
        await asyncio.shield(future)

    async def reserve(self, key: ConversationKey) -> ConversationCapacityReservation:
        async with self._condition:
            while not self._stopping and (self._pending_count >= self.max_pending):
                self._backpressure_waits += 1
                await self._condition.wait()
            if self._stopping:
                raise RuntimeError("conversation scheduler is stopping")
            self._pending_count += 1
            self._pending_by_key[key] = self._pending_by_key.get(key, 0) + 1
            self._record_peaks_locked()
            return ConversationCapacityReservation(scheduler=self, key=key)

    async def release_reservation(self, reservation: ConversationCapacityReservation) -> None:
        async with self._condition:
            self._release_reservation_locked(reservation)

    def _release_reservation_locked(self, reservation: ConversationCapacityReservation) -> None:
        if reservation.scheduler is not self or reservation._queued or reservation._released:
            return
        reservation._released = True
        self._release_pending_locked(reservation.key)
        self._condition.notify_all()

    async def wait_for_capacity(self) -> None:
        async with self._condition:
            while not self._stopping and self._pending_count >= self.max_pending:
                self._backpressure_waits += 1
                await self._condition.wait()
            if self._stopping:
                raise RuntimeError("conversation scheduler is stopping")

    async def set_concurrency(self, concurrency: int) -> None:
        async with self._condition:
            self.concurrency = max(1, int(concurrency))
            self._start_ready_locked()
            self._condition.notify_all()

    async def stop(self) -> None:
        async with self._condition:
            if self._stopping:
                return
            self._stopping = True
            queued = [item for queue in self._queues.values() for item in queue]
            queued_keys = [key for key, queue in self._queues.items() for _ in queue]
            self._queues.clear()
            self._ready.clear()
            self._ready_keys.clear()
            for key in queued_keys:
                self._release_pending_locked(key)
                self._release_scheduled_locked(key)
            for item in queued:
                if not item.future.done():
                    item.future.cancel()
            tasks = tuple(self._tasks)
            self._condition.notify_all()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_for_pending_at_least(self, count: int) -> None:
        async with self._condition:
            while not self._stopping and self._pending_count < count:
                await self._condition.wait()

    def snapshot(self) -> dict[str, int | float]:
        ordered = sorted(self._wait_samples_ms)
        wait_p95 = None
        if ordered:
            index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95)))
            wait_p95 = round(ordered[index], 2)
        return {
            "concurrency": self.concurrency,
            "pending": self._pending_count,
            "pending_peak": self._pending_peak,
            "active": len(self._running_keys),
            "active_peak": self._active_peak,
            "ready": len(self._ready),
            "ready_peak": self._ready_peak,
            "max_pending": self.max_pending,
            "per_key_pending_limit": self.per_key_pending,
            "active_keys": len(self._pending_by_key),
            "wait_ms_p95": wait_p95,
            "backpressure_waits": self._backpressure_waits,
            "per_key_backpressure_waits": self._per_key_backpressure_waits,
        }

    def _record_peaks_locked(self) -> None:
        self._pending_peak = max(self._pending_peak, self._pending_count)
        self._ready_peak = max(self._ready_peak, len(self._ready))
        self._active_peak = max(self._active_peak, len(self._running_keys))

    def _release_pending_locked(self, key: ConversationKey) -> None:
        self._pending_count = max(0, self._pending_count - 1)
        remaining = self._pending_by_key.get(key, 0) - 1
        if remaining > 0:
            self._pending_by_key[key] = remaining
        else:
            self._pending_by_key.pop(key, None)

    def _release_scheduled_locked(self, key: ConversationKey) -> None:
        remaining = self._scheduled_by_key.get(key, 0) - 1
        if remaining > 0:
            self._scheduled_by_key[key] = remaining
        else:
            self._scheduled_by_key.pop(key, None)

    def _queue_ready_key_locked(self, key: ConversationKey) -> None:
        if key in self._running_keys or key in self._ready_keys:
            return
        if not self._queues.get(key):
            return
        self._ready.append(key)
        self._ready_keys.add(key)

    def _start_ready_locked(self) -> None:
        while not self._stopping and len(self._running_keys) < self.concurrency and self._ready:
            key = self._ready.popleft()
            self._ready_keys.discard(key)
            if key in self._running_keys or not self._queues.get(key):
                continue
            self._running_keys.add(key)
            self._record_peaks_locked()
            task = asyncio.create_task(self._run_one(key), name=f"conversation_scheduler:{key[0]}:{key[1]}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_one(self, key: ConversationKey) -> None:
        item: ConversationWork | None = None
        try:
            async with self._condition:
                queue = self._queues.get(key)
                if queue:
                    item = queue.popleft()
                    if not queue:
                        self._queues.pop(key, None)
            if item is None:
                return
            self._wait_samples_ms.append((time.monotonic() - item.queued_at) * 1000.0)
            try:
                await item.work()
            except asyncio.CancelledError:
                if not item.future.done():
                    item.future.cancel()
                raise
            except Exception as exc:
                if not item.future.done():
                    item.future.set_exception(exc)
            else:
                if not item.future.done():
                    item.future.set_result(None)
        finally:
            async with self._condition:
                if item is not None:
                    self._release_pending_locked(key)
                    self._release_scheduled_locked(key)
                self._running_keys.discard(key)
                if not self._stopping:
                    self._queue_ready_key_locked(key)
                    self._start_ready_locked()
                self._condition.notify_all()


_scheduler: ConversationScheduler | None = None
_active_reservation: ContextVar[ConversationCapacityReservation | None] = ContextVar(
    "conversation_capacity_reservation",
    default=None,
)


def conversation_scheduler_enabled() -> bool:
    return get_ingress_dispatch_runtime_config().conversation_scheduler_enabled


def conversation_key(bot: Bot, event: Event) -> ConversationKey | None:
    if not isinstance(event, GroupMessageEvent):
        return None
    return (str(bot.self_id), int(event.group_id))


async def start_conversation_scheduler() -> None:
    global _scheduler
    if _scheduler is not None or not conversation_scheduler_enabled():
        return
    config = get_ingress_dispatch_runtime_config()
    _scheduler = ConversationScheduler(
        concurrency=config.conversation_scheduler_concurrency,
        max_pending=config.conversation_scheduler_max_pending,
        per_key_pending=config.conversation_scheduler_per_key_pending,
    )


async def stop_conversation_scheduler() -> None:
    global _scheduler
    scheduler = _scheduler
    _scheduler = None
    if scheduler is not None:
        await scheduler.stop()


async def set_conversation_scheduler_concurrency(concurrency: int) -> bool:
    scheduler = _scheduler
    if scheduler is None:
        return False
    await scheduler.set_concurrency(concurrency)
    return True


async def submit_conversation_event(bot: Bot, event: Event, work: Work) -> None:
    scheduler = _scheduler
    key = conversation_key(bot, event)
    reservation = _active_reservation.get()
    if scheduler is None:
        if reservation is not None:
            await reservation.release()
            raise RuntimeError("conversation scheduler is stopping")
        await work()
        return
    if key is None:
        await work()
        return
    if reservation is not None and reservation.scheduler is not scheduler:
        await reservation.release()
        reservation = None
    await scheduler.submit(key, work, reservation=reservation)


async def reserve_conversation_capacity(
    bot: Bot,
    event: Event,
) -> ConversationCapacityReservation | None:
    scheduler = _scheduler
    key = conversation_key(bot, event)
    if scheduler is None or key is None:
        return None
    return await scheduler.reserve(key)


async def run_conversation_event_with_reservation(
    bot: Bot,
    event: Event,
    reservation: ConversationCapacityReservation | None,
) -> None:
    token: Token[ConversationCapacityReservation | None] | None = None
    if reservation is not None:
        token = _active_reservation.set(reservation)
    try:
        await bot.handle_event(event)
    finally:
        if token is not None:
            _active_reservation.reset(token)
        if reservation is not None:
            await reservation.release()


async def wait_for_conversation_capacity(bot: Bot, event: Event) -> None:
    scheduler = _scheduler
    if scheduler is None or conversation_key(bot, event) is None:
        return
    await scheduler.wait_for_capacity()


def conversation_scheduler_status() -> dict[str, int | float | bool | None]:
    scheduler = _scheduler
    if scheduler is None:
        config = get_ingress_dispatch_runtime_config()
        return {
            "enabled": config.conversation_scheduler_enabled,
            "concurrency": config.conversation_scheduler_concurrency,
            "pending": 0,
            "pending_peak": 0,
            "active": 0,
            "active_peak": 0,
            "ready": 0,
            "ready_peak": 0,
            "max_pending": config.conversation_scheduler_max_pending,
            "per_key_pending_limit": config.conversation_scheduler_per_key_pending,
            "active_keys": 0,
            "wait_ms_p95": None,
            "backpressure_waits": 0,
            "per_key_backpressure_waits": 0,
        }
    return {"enabled": True, **scheduler.snapshot()}


def reset_conversation_scheduler_for_tests() -> None:
    global _scheduler
    _scheduler = None
