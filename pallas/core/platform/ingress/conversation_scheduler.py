from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from pallas.core.platform.ingress.cold_start import in_cold_start_window
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
    mode: str


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
    def __init__(
        self,
        *,
        concurrency: int,
        max_pending: int,
        per_key_pending: int | None = None,
        llm_reserved: int = 0,
    ) -> None:
        self.concurrency = max(1, int(concurrency))
        self.max_pending = max(1, int(max_pending))
        self.per_key_pending = max(1, int(per_key_pending if per_key_pending is not None else self.max_pending))
        self.llm_reserved = max(0, min(int(llm_reserved), self.concurrency - 1))
        self._queues: dict[ConversationKey, deque[ConversationWork]] = {}
        self._ready: deque[ConversationKey] = deque()
        self._ready_keys: set[ConversationKey] = set()
        self._running_keys: set[ConversationKey] = set()
        self._running_by_key: dict[ConversationKey, int] = {}
        self._active_count = 0
        self._llm_waiting = 0
        self._llm_active = 0
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
        self._run_samples_ms: deque[float] = deque(maxlen=256)
        self._stopping = False
        self._condition = asyncio.Condition()

    async def submit(
        self,
        key: ConversationKey,
        work: Work,
        *,
        reservation: ConversationCapacityReservation | None = None,
        mode: str = "serial",
    ) -> None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        item = ConversationWork(work=work, future=future, queued_at=time.monotonic(), mode=mode)
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
            if mode == "llm":
                self._llm_waiting += 1
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

    async def set_llm_reserved(self, reserved: int) -> None:
        async with self._condition:
            self.llm_reserved = max(0, min(int(reserved), self.concurrency - 1))
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
                if item.mode == "llm":
                    self._llm_waiting = max(0, self._llm_waiting - 1)
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
        run_ordered = sorted(self._run_samples_ms)
        run_p95 = None
        if run_ordered:
            index = max(0, min(len(run_ordered) - 1, int(len(run_ordered) * 0.95)))
            run_p95 = round(run_ordered[index], 2)
        return {
            "concurrency": self.concurrency,
            "llm_reserved": self.llm_reserved,
            "llm_waiting": self._llm_waiting,
            "llm_active": self._llm_active,
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
            "run_ms_p95": run_p95,
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
        if key in self._ready_keys:
            return
        if not self._queues.get(key):
            return
        running = self._running_by_key.get(key, 0)
        if running and any(item.mode != "chat" for item in self._queues[key]):
            return
        if running >= 2:
            return
        self._ready.append(key)
        self._ready_keys.add(key)

    def _start_ready_locked(self) -> None:
        attempts = len(self._ready)
        while not self._stopping and self._active_count < self.concurrency and self._ready and attempts:
            attempts -= 1
            key = self._ready.popleft()
            self._ready_keys.discard(key)
            if not self._queues.get(key):
                continue
            running = self._running_by_key.get(key, 0)
            queue = self._queues[key]
            serial_index = next((index for index, item in enumerate(queue) if item.mode != "chat"), None)
            if serial_index is not None and running:
                continue
            if serial_index is not None:
                item = queue[serial_index]
                del queue[serial_index]
            elif running >= 2:
                continue
            else:
                item = queue.popleft()
            if item.mode != "llm" and self._llm_waiting > 0:
                ordinary_limit = self.concurrency - self.llm_reserved
                if self._active_count >= ordinary_limit:
                    queue.appendleft(item)
                    self._ready.append(key)
                    self._ready_keys.add(key)
                    continue
            if not queue:
                self._queues.pop(key, None)
            self._running_keys.add(key)
            self._running_by_key[key] = running + 1
            self._active_count += 1
            if item.mode == "llm":
                self._llm_waiting = max(0, self._llm_waiting - 1)
                self._llm_active += 1
            self._record_peaks_locked()
            task = asyncio.create_task(self._run_one(key, item), name=f"conversation_scheduler:{key[0]}:{key[1]}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_one(self, key: ConversationKey, item: ConversationWork) -> None:
        started = time.monotonic()
        try:
            self._wait_samples_ms.append((started - item.queued_at) * 1000.0)
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
            self._run_samples_ms.append((time.monotonic() - started) * 1000.0)
            async with self._condition:
                if item is not None:
                    self._release_pending_locked(key)
                    self._release_scheduled_locked(key)
                    self._active_count = max(0, self._active_count - 1)
                    if item.mode == "llm":
                        self._llm_active = max(0, self._llm_active - 1)
                running = self._running_by_key.get(key, 1) - 1
                if running > 0:
                    self._running_by_key[key] = running
                else:
                    self._running_by_key.pop(key, None)
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
    target = config.conversation_scheduler_concurrency
    startup = min(config.conversation_scheduler_startup_concurrency, target)
    _scheduler = ConversationScheduler(
        concurrency=startup,
        max_pending=config.conversation_scheduler_max_pending,
        per_key_pending=config.conversation_scheduler_per_key_pending,
        llm_reserved=config.conversation_scheduler_llm_reserved,
    )
    if startup < target:
        asyncio.create_task(_ramp_up_scheduler(_scheduler), name="conversation_scheduler_startup_ramp")


async def _ramp_up_scheduler(scheduler: ConversationScheduler) -> None:
    """冷启动窗口内把调度并发渐进到目标，窗口结束或达目标后一次到位。"""
    config = get_ingress_dispatch_runtime_config()
    target = config.conversation_scheduler_concurrency
    startup = config.conversation_scheduler_startup_concurrency
    interval = config.conversation_scheduler_adaptive_interval_sec
    while True:
        if scheduler._stopping or scheduler.concurrency >= target:
            break
        if not in_cold_start_window():
            break
        await asyncio.sleep(interval)
        await scheduler.set_concurrency(min(target, scheduler.concurrency + startup))
    await scheduler.set_concurrency(target)
    await scheduler.set_llm_reserved(config.conversation_scheduler_llm_reserved)


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
    from pallas.core.platform.ingress.matcher_activation import legacy_command_traffic

    plain = str(getattr(event, "get_plaintext", lambda: "")() or "").strip()
    is_command = legacy_command_traffic(plain, group_only=True) or plain in {"牛牛", "帕拉斯"}
    mode = (
        "llm"
        if not is_command
        and (
            getattr(event, "to_me", False)
            or getattr(event, "_pallas_llm_alias_hard_trigger", False)
            or getattr(event, "_pallas_llm_at_trigger", False)
        )
        else ("serial" if is_command else "chat")
    )
    await scheduler.submit(key, work, reservation=reservation, mode=mode)


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
            "run_ms_p95": None,
            "backpressure_waits": 0,
            "per_key_backpressure_waits": 0,
        }
    return {"enabled": True, **scheduler.snapshot()}


def reset_conversation_scheduler_for_tests() -> None:
    global _scheduler
    _scheduler = None
