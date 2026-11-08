from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from threading import Event, Lock, RLock
from typing import TYPE_CHECKING, Any

from nonebot import logger

from pallas.core.foundation.command_prefix import matches_command_prefix
from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.logging import log_rate_limited
from pallas.core.platform.ingress.dream_host_gate import DREAM_HOST_GATE_PLUGIN
from pallas.core.platform.ingress.hosted_activity_gate import (
    loaded_hosted_activity_specs,
    spec_matches_in_room_command,
    spec_matches_speak_traffic,
)
from pallas.core.platform.multi_bot.dedup import needs_group_host_bot_gate
from pallas.core.platform.shard.coord.group_gate import read_owned_gate_bot_id_sync
from pallas.core.platform.shard.coord.hosted_activity_coord import hosted_activity_live

if TYPE_CHECKING:
    from collections.abc import Callable

GATE_EXECUTOR_THREAD_PREFIX = "pallas-ingress-gate"
_GATE_WORKERS = 6
_GATE_QUEUE_CAPACITY = 12
_GATE_MAX_WAITERS = 64
_GATE_ADMISSION_WAIT_SEC = 0.25
_GATE_QUEUE_WARN_MS = 1000.0

_executor: ThreadPoolExecutor | None = None
_executor_closed = False
_owner_loop: asyncio.AbstractEventLoop | None = None
_gate_lifecycle_lock = RLock()
_gate_slots = asyncio.BoundedSemaphore(_GATE_QUEUE_CAPACITY)
_gate_waiters = 0
_submitted_work: set[_GateCall] = set()
_submitted_work_lock = Lock()


class GateNotStarted(Enum):
    SATURATED = "saturated"
    WAIT_TIMEOUT = "wait_timeout"
    SHUTDOWN = "shutdown"
    CANCELLED = "cancelled"
    LOOP_MISMATCH = "loop_mismatch"


class GateExecutionTimeout(Enum):
    RUNNING = "running_timeout"


class _GateCall:
    def __init__(
        self,
        func,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        loop: asyncio.AbstractEventLoop,
        slots: asyncio.BoundedSemaphore,
        deadline: float,
    ) -> None:
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.loop = loop
        self.slots = slots
        self.deadline = deadline
        self.started_future: asyncio.Future[float] = loop.create_future()
        self._submission_settled = Event()
        self._lock = Lock()
        self._started = False
        self._started_at: float | None = None
        self._skip_result: GateNotStarted | None = None

    def skip_if_not_started(self, result: GateNotStarted) -> GateNotStarted | None:
        with self._lock:
            if self._started:
                return None
            if self._skip_result is None:
                self._skip_result = result
            return self._skip_result

    def settle_submission(self, result: GateNotStarted | None = None) -> None:
        if result is not None:
            with self._lock:
                if not self._started and self._skip_result is None:
                    self._skip_result = result
        self._submission_settled.set()

    def start_state(self) -> tuple[bool, float | None]:
        with self._lock:
            return self._started, self._started_at

    def notify_started(self, started_at: float) -> None:
        if not self.started_future.done():
            self.started_future.set_result(started_at)

    def __call__(self):
        self._submission_settled.wait()
        started_at = time.monotonic()
        with self._lock:
            result = self._skip_result
            if result is None and started_at >= self.deadline:
                result = self._skip_result = GateNotStarted.WAIT_TIMEOUT
            self._started = True
            if result is None:
                self._started_at = started_at
        try:
            self.loop.call_soon_threadsafe(_release_gate_slot, self.slots)
            if result is None:
                self.loop.call_soon_threadsafe(self.notify_started, started_at)
        except RuntimeError:
            return GateNotStarted.SHUTDOWN
        if result is not None:
            return result
        return self.func(*self.args, **self.kwargs)


def _release_gate_slot(slots: asyncio.BoundedSemaphore) -> None:
    slots.release()


def _consume_future_exception(future: asyncio.Future[Any]) -> None:
    if not future.cancelled():
        future.exception()


def _log_gate_not_started(result: GateNotStarted, func: Any) -> GateNotStarted:
    log_rate_limited(
        logger,
        "warning",
        "gate_pool_not_started",
        "Ingress gate task [{}] was not started because admission was [{}].",
        getattr(func, "__name__", "?"),
        result.value,
    )
    return result


def gate_queue_warn_ms() -> float:
    """排队超过这个时长就记一条限频告警，用来确认专用池没有被 Redis 停滞拖住。"""
    raw = repo_env_raw_value("PALLAS_GATE_QUEUE_WARN_MS")
    if raw is None:
        return _GATE_QUEUE_WARN_MS
    try:
        return max(100.0, float(str(raw).strip()))
    except ValueError:
        return _GATE_QUEUE_WARN_MS


def gate_executor() -> ThreadPoolExecutor:
    global _executor
    with _gate_lifecycle_lock:
        if _executor_closed:
            raise RuntimeError("gate executor has been shut down")
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=_GATE_WORKERS,
                thread_name_prefix=GATE_EXECUTOR_THREAD_PREFIX,
            )
        return _executor


async def run_gate_blocking[T](
    func: Callable[..., T], /, *args: Any, _running_timeout_sec: float | None = None, **kwargs: Any
) -> T | GateNotStarted | GateExecutionTimeout:
    """在有界 gate 池运行同步判定；未能开始时返回 GateNotStarted，不抛过载异常。

    Redis 协调判定必须离开事件循环；``to_thread`` 用的是默认池，PG 抖动时这里会排在队尾，
    单独一条通道能让入站请求的 p99 不再跟着 DB 一起抖。最多 12 个任务排队、64 个调用等待；
    250ms deadline 覆盖准入和 executor 排队；已开始的任务默认继续等待，可选运行时限不取消线程。
    """
    loop = asyncio.get_running_loop()
    deadline = time.monotonic() + _GATE_ADMISSION_WAIT_SEC
    global _owner_loop, _executor_closed
    with _gate_lifecycle_lock:
        if _executor_closed:
            return _log_gate_not_started(GateNotStarted.SHUTDOWN, func)
        if _owner_loop is None:
            _owner_loop = loop
        elif _owner_loop is not loop:
            return _log_gate_not_started(GateNotStarted.LOOP_MISMATCH, func)
        slots = _gate_slots

    global _gate_waiters
    if slots.locked():
        if _gate_waiters >= _GATE_MAX_WAITERS:
            return _log_gate_not_started(GateNotStarted.SATURATED, func)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            with _gate_lifecycle_lock:
                result = GateNotStarted.SHUTDOWN if _executor_closed else GateNotStarted.WAIT_TIMEOUT
            return _log_gate_not_started(result, func)
        _gate_waiters += 1
        try:
            try:
                await asyncio.wait_for(slots.acquire(), timeout=remaining)
            except TimeoutError:
                with _gate_lifecycle_lock:
                    result = GateNotStarted.SHUTDOWN if _executor_closed else GateNotStarted.WAIT_TIMEOUT
                return _log_gate_not_started(result, func)
        finally:
            _gate_waiters -= 1
    else:
        await slots.acquire()

    if time.monotonic() >= deadline:
        slots.release()
        with _gate_lifecycle_lock:
            result = GateNotStarted.SHUTDOWN if _executor_closed else GateNotStarted.WAIT_TIMEOUT
        return _log_gate_not_started(result, func)

    submitted = time.monotonic()
    started: list[float] = []

    def _invoke(call: _GateCall) -> T | GateNotStarted:
        started.append(time.monotonic())
        try:
            return call()
        finally:
            with _submitted_work_lock:
                _submitted_work.discard(call)

    call = _GateCall(func, args, kwargs, loop, slots, deadline)
    submission_error: GateNotStarted | None = None
    submission_failure: BaseException | None = None
    with _gate_lifecycle_lock:
        if _executor_closed:
            submission_error = GateNotStarted.SHUTDOWN
        elif _owner_loop is not loop:
            submission_error = GateNotStarted.LOOP_MISMATCH
        else:
            with _submitted_work_lock:
                _submitted_work.add(call)
            try:
                future = gate_executor().submit(_invoke, call)
            except BaseException as exc:
                # submit may enqueue before worker startup fails; poison the pool and keep its slot.
                call.settle_submission(GateNotStarted.SHUTDOWN)
                with _submitted_work_lock:
                    _submitted_work.discard(call)
                    pending = tuple(_submitted_work)
                _executor_closed = True
                for pending_call in pending:
                    pending_call.skip_if_not_started(GateNotStarted.SHUTDOWN)
                submission_failure = exc
            else:
                call.settle_submission()
    if submission_failure is not None:
        if isinstance(submission_failure, RuntimeError):
            return _log_gate_not_started(GateNotStarted.SHUTDOWN, func)
        raise submission_failure
    if submission_error is not None:
        slots.release()
        return _log_gate_not_started(submission_error, func)

    wrapped = asyncio.wrap_future(future, loop=loop)
    try:
        while not wrapped.done():
            is_started, started_at = call.start_state()
            if is_started:
                if started_at is None or _running_timeout_sec is None:
                    break
                remaining = started_at + max(0.0, _running_timeout_sec) - time.monotonic()
                if remaining <= 0:
                    if wrapped.done():
                        break
                    wrapped.add_done_callback(_consume_future_exception)
                    return GateExecutionTimeout.RUNNING
                done, _ = await asyncio.wait((wrapped,), timeout=remaining)
                if not done and not wrapped.done():
                    wrapped.add_done_callback(_consume_future_exception)
                    return GateExecutionTimeout.RUNNING
                continue

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                skipped = call.skip_if_not_started(GateNotStarted.WAIT_TIMEOUT)
                if skipped is not None:
                    return _log_gate_not_started(skipped, func)
                continue
            done, _ = await asyncio.wait(
                (wrapped, call.started_future),
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if wrapped in done or call.started_future in done:
                continue
            skipped = call.skip_if_not_started(GateNotStarted.WAIT_TIMEOUT)
            if skipped is not None:
                return _log_gate_not_started(skipped, func)

        result = await wrapped
    except asyncio.CancelledError:
        call.skip_if_not_started(GateNotStarted.CANCELLED)
        wrapped.add_done_callback(_consume_future_exception)
        raise
    if started:
        queued_ms = (started[0] - submitted) * 1000.0
        if queued_ms >= gate_queue_warn_ms():
            log_rate_limited(
                logger,
                "warning",
                "gate_pool_queue",
                "gate 专用池排队 [{}]ms，任务 [{}]",
                round(queued_ms),
                getattr(func, "__name__", "?"),
            )
    return result


def shutdown_gate_executor() -> None:
    """停机时丢弃排队任务；在途任务不等待，避免拖住 NoneBot 关闭。"""
    global _executor, _executor_closed
    with _gate_lifecycle_lock:
        _executor_closed = True
        executor = _executor
        _executor = None
        with _submitted_work_lock:
            pending = tuple(_submitted_work)
        for call in pending:
            call.skip_if_not_started(GateNotStarted.SHUTDOWN)
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=False)


def ingress_once_claim_safe_before_host_gates(
    group_id: int,
    plain: str,
    *,
    at_fleet_bot: bool,
) -> bool:
    if not needs_group_host_bot_gate():
        return True

    gid = int(group_id)
    text = (plain or "").strip()
    for spec in loaded_hosted_activity_specs():
        in_room = spec_matches_in_room_command(spec, plain)
        speak = spec_matches_speak_traffic(spec, gid, plain, at_fleet_bot=at_fleet_bot)
        open_or_end = any(matches_command_prefix(text, prefix) for prefix in spec.always_pass_prefixes)
        if not in_room and not speak and not open_or_end:
            continue
        if hosted_activity_live(
            activity_namespace=spec.activity_namespace,
            plugin_key=spec.plugin_key,
            group_id=gid,
        ):
            return False

    if read_owned_gate_bot_id_sync(DREAM_HOST_GATE_PLUGIN, gid) is not None:
        return False
    return True
