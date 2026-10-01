from __future__ import annotations

import asyncio
import contextvars
import time
from dataclasses import dataclass
from typing import Any

from nonebot.log import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.logging.bridge import format_business_event
from pallas.core.foundation.logging.throttle import log_rate_limited

_ORIGINAL_CALL_API = None
_PATCHED = False
_BYPASS = contextvars.ContextVar("_ingress_send_queue_bypass", default=False)

_QUEUE: asyncio.PriorityQueue[tuple[int, int, SendQueueItem]] | None = None
_WORKERS: list[asyncio.Task[None]] = []
_RETRY_TASKS: set[asyncio.Task[None]] = set()
_ACTIVE_ITEMS: set[SendQueueItem] = set()
_CAPACITY_CHANGED: asyncio.Event | None = None
_STOP_COMPLETE: asyncio.Event | None = None
_STOP_TASK: asyncio.Task[None] | None = None
_SEQ = 0
_GENERATION = 0
_STOPPING = False
_STATS = {
    "enqueued": 0,
    "sent": 0,
    "dropped": 0,
    "errors": 0,
    "retries": 0,
    "retry_dropped": 0,
    "risk_cooldowns": 0,
    "depth": 0,
}
_ERROR_DIMENSION_LIMIT = 16
_ERRORS_BY_API: dict[str, int] = {}
_ERRORS_BY_CLASS: dict[str, int] = {}
_ERRORS_BY_RETCODE: dict[str, int] = {}
_ERRORS_BY_REASON: dict[str, int] = {}
_LAST_ERROR: dict[str, Any] | None = None
_LAST_ERROR_AT = 0.0
_LAST_SEND_AT: dict[str, float] = {}
_RISK_STREAK: dict[str, int] = {}
_RISK_COOLDOWN_UNTIL: dict[str, float] = {}
_RETRY_COUNTS: dict[str, int] = {}

_HIGH_PRIORITY_APIS = frozenset({
    "send_group_msg",
    "send_private_msg",
    "send_msg",
    "send_group_forward_msg",
    "send_private_forward_msg",
})
_DROPPABLE_APIS = frozenset({
    "set_msg_emoji_like",
    "send_like",
})
_QUEUED_APIS = _HIGH_PRIORITY_APIS | _DROPPABLE_APIS | frozenset({"group_poke"})


@dataclass(slots=True, eq=False)
class SendQueueItem:
    adapter: Any
    bot: Any
    api: str
    data: dict[str, Any]
    future: asyncio.Future[Any]
    attempt: int = 0
    generation: int = 0
    completed: bool = False
    retry_task: asyncio.Task[None] | None = None


def send_queue_enabled() -> bool:
    raw = repo_env_raw_value("PALLAS_SEND_QUEUE_ENABLED")
    if raw is None:
        return True
    text = str(raw).strip().lower()
    if text in ("0", "false", "no", "off"):
        return False
    return True


def send_queue_worker_count() -> int:
    raw = repo_env_raw_value("PALLAS_SEND_QUEUE_WORKERS")
    if raw is None:
        return 2
    try:
        return max(1, min(16, int(str(raw).strip())))
    except ValueError:
        return 2


def send_queue_max_depth() -> int:
    raw = repo_env_raw_value("PALLAS_SEND_QUEUE_MAX_DEPTH")
    if raw is None:
        return 256
    try:
        return max(16, int(str(raw).strip()))
    except ValueError:
        return 256


def send_queue_min_interval_sec() -> float:
    raw = repo_env_raw_value("PALLAS_SEND_QUEUE_MIN_INTERVAL_MS")
    if raw is None:
        return 0.05
    try:
        return max(0.0, float(str(raw).strip()) / 1000.0)
    except ValueError:
        return 0.05


def send_queue_enqueue_timeout_sec() -> float:
    raw = repo_env_raw_value("PALLAS_SEND_QUEUE_ENQUEUE_TIMEOUT_SEC")
    if raw is None:
        return 2.0
    try:
        return max(0.1, float(str(raw).strip()))
    except ValueError:
        return 2.0


def send_queue_retry_max() -> int:
    raw = repo_env_raw_value("PALLAS_SEND_RETRY_MAX")
    if raw is None:
        return 2
    try:
        return max(0, min(5, int(str(raw).strip())))
    except ValueError:
        return 2


def send_queue_retry_backoff_base_sec() -> float:
    raw = repo_env_raw_value("PALLAS_SEND_RETRY_BACKOFF_BASE_SEC")
    if raw is None:
        return 1.0
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return 1.0


def send_queue_retry_risk_cooldown_sec() -> float:
    raw = repo_env_raw_value("PALLAS_SEND_RETRY_RISK_COOLDOWN_SEC")
    if raw is None:
        return 30.0
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return 30.0


def send_queue_retry_risk_latch_times() -> int:
    raw = repo_env_raw_value("PALLAS_SEND_RETRY_RISK_LATCH_TIMES")
    if raw is None:
        return 3
    try:
        return max(1, min(10, int(str(raw).strip())))
    except ValueError:
        return 3


def api_send_priority(api: str) -> int:
    if api in _HIGH_PRIORITY_APIS:
        return 0
    return 10


def should_queue_api(api: str) -> bool:
    return api in _QUEUED_APIS


def is_droppable_api(api: str) -> bool:
    return api in _DROPPABLE_APIS


def send_queue_status() -> dict[str, Any]:
    depth = _STATS["depth"]
    last_error = None
    if _LAST_ERROR is not None:
        last_error = {
            **_LAST_ERROR,
            "age_sec": round(max(0.0, time.monotonic() - _LAST_ERROR_AT), 2),
        }
    return {
        "enabled": send_queue_enabled(),
        "installed": _PATCHED,
        "depth": depth,
        "max_depth": send_queue_max_depth(),
        "workers": send_queue_worker_count(),
        "min_interval_ms": send_queue_min_interval_sec() * 1000.0,
        "retry_max": send_queue_retry_max(),
        "retry_backoff_base_sec": send_queue_retry_backoff_base_sec(),
        "retry_risk_cooldown_sec": send_queue_retry_risk_cooldown_sec(),
        "risk_latch_times": send_queue_retry_risk_latch_times(),
        **dict(_STATS),
        "errors_by_api": dict(_ERRORS_BY_API),
        "errors_by_class": dict(_ERRORS_BY_CLASS),
        "errors_by_retcode": dict(_ERRORS_BY_RETCODE),
        "errors_by_reason": dict(_ERRORS_BY_REASON),
        "last_error": last_error,
        "depth_live": depth,
    }


def reset_send_queue_for_tests() -> None:
    global _SEQ, _PATCHED, _ORIGINAL_CALL_API, _LAST_ERROR, _LAST_ERROR_AT
    _SEQ = 0
    _PATCHED = False
    _ORIGINAL_CALL_API = None
    for key in _STATS:
        _STATS[key] = 0
    _ERRORS_BY_API.clear()
    _ERRORS_BY_CLASS.clear()
    _ERRORS_BY_RETCODE.clear()
    _ERRORS_BY_REASON.clear()
    _LAST_ERROR = None
    _LAST_ERROR_AT = 0.0
    _LAST_SEND_AT.clear()
    _RISK_STREAK.clear()
    _RISK_COOLDOWN_UNTIL.clear()
    _RETRY_COUNTS.clear()


def classify_send_queue_error(api: str, exc: Exception) -> str:
    info = getattr(exc, "info", None)
    detail = ""
    if isinstance(info, dict):
        detail = " ".join(str(info.get(key) or "") for key in ("message", "wording", "msg")).lower()
    if api == "set_msg_emoji_like" and ("already set" in detail or "已经设置过" in detail or "65002" in detail):
        return "already_reacted"
    if api == "set_msg_emoji_like" and "message not found" in detail:
        return "message_not_found"
    if api in _HIGH_PRIORITY_APIS and ("removed from the group" in detail or "已被移出该群" in detail):
        return "bot_not_in_group"
    if api in _HIGH_PRIORITY_APIS and "http download failed" in detail:
        return "media_download_failed"
    return "other"


def record_send_queue_error(api: str, exc: Exception) -> None:
    global _LAST_ERROR, _LAST_ERROR_AT
    error_class = type(exc).__name__
    info = getattr(exc, "info", None)
    retcode = info.get("retcode") if isinstance(info, dict) else None
    if not isinstance(retcode, int) or isinstance(retcode, bool):
        retcode = None
    reason = classify_send_queue_error(api, exc)

    def increment(counter: dict[str, int], key: str) -> None:
        if key not in counter and len(counter) >= _ERROR_DIMENSION_LIMIT - 1:
            key = "other"
        counter[key] = counter.get(key, 0) + 1

    increment(_ERRORS_BY_API, str(api))
    increment(_ERRORS_BY_CLASS, error_class)
    if retcode is not None:
        increment(_ERRORS_BY_RETCODE, str(retcode))
    increment(_ERRORS_BY_REASON, reason)
    _LAST_ERROR = {
        "api": str(api),
        "error_class": error_class,
        "retcode": retcode,
        "reason": reason,
    }
    _LAST_ERROR_AT = time.monotonic()


def is_ambiguous_send_timeout(exc: Exception) -> bool:
    """请求已写入 socket 但回执超时：消息可能已投递，重试会重复发送。"""
    return "timeout" in str(exc or "").lower()


def is_retryable_send_error(api: str, exc: Exception) -> bool:
    from nonebot.adapters.onebot.v11 import ActionFailed

    if isinstance(exc, ActionFailed):
        reason = classify_send_queue_error(api, exc)
        return reason == "media_download_failed"
    from nonebot.adapters.onebot.v11 import NetworkError

    if not isinstance(exc, NetworkError):
        return False
    # WebSocket 超时说明请求已发送但回执丢失，消息可能已投递，重试会导致重复音频/消息
    return not is_ambiguous_send_timeout(exc)


def is_risk_limited_send_error(api: str, exc: Exception) -> bool:
    from nonebot.adapters.onebot.v11 import ActionFailed

    if not isinstance(exc, ActionFailed):
        return False
    info = getattr(exc, "info", None)
    if not isinstance(info, dict):
        return False
    retcode = info.get("retcode")
    if retcode == 1201:
        return True
    detail = " ".join(str(info.get(key) or "") for key in ("message", "wording", "msg")).lower()
    return any(word in detail for word in ("too frequently", "过于频繁", "频率过高", "message too often"))


def send_error_retry_delay_sec(api: str, exc: Exception, attempt: int) -> float:
    base = send_queue_retry_backoff_base_sec()
    if is_risk_limited_send_error(api, exc):
        return send_queue_retry_risk_cooldown_sec()
    return base * (2 ** max(0, attempt - 1))


def is_send_bot_in_risk_cooldown(bot_self_id: str) -> float:
    until = _RISK_COOLDOWN_UNTIL.get(bot_self_id, 0.0)
    return max(0.0, until - time.monotonic())


def note_send_risk_failure(bot_self_id: str) -> None:
    streak = _RISK_STREAK.get(bot_self_id, 0) + 1
    latch_times = send_queue_retry_risk_latch_times()
    if streak >= latch_times:
        _RISK_STREAK[bot_self_id] = 0
        _RISK_COOLDOWN_UNTIL[bot_self_id] = time.monotonic() + send_queue_retry_risk_cooldown_sec()
        _STATS["risk_cooldowns"] += 1
        log_rate_limited(
            logger,
            "warning",
            f"send_queue.risk_cooldown.{bot_self_id}",
            "Send queue risk cooldown armed for bot [{}] after [{}] consecutive rate-limit failures",
            bot_self_id,
            latch_times,
        )
    else:
        _RISK_STREAK[bot_self_id] = streak


async def _rate_limit_wait(bot_self_id: str) -> None:
    interval = send_queue_min_interval_sec()
    if interval <= 0:
        return
    now = time.monotonic()
    last = _LAST_SEND_AT.get(bot_self_id, 0.0)
    delay = interval - (now - last)
    if delay > 0:
        await asyncio.sleep(delay)
    _LAST_SEND_AT[bot_self_id] = time.monotonic()


def _finish_queue_item(item: SendQueueItem, *, result: Any = None, error: BaseException | None = None) -> None:
    if item.completed:
        return
    item.completed = True
    if item not in _ACTIVE_ITEMS:
        return
    _ACTIVE_ITEMS.remove(item)
    _STATS["depth"] = max(0, _STATS["depth"] - 1)
    if _CAPACITY_CHANGED is not None:
        _CAPACITY_CHANGED.set()
    if not item.future.done():
        if error is not None:
            item.future.set_exception(error)
        else:
            item.future.set_result(result)


async def _requeue_item_with_delay(item: SendQueueItem, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        _finish_queue_item(item, error=RuntimeError("send_queue stopped during retry"))
        raise
    finally:
        if item.retry_task is asyncio.current_task():
            item.retry_task = None
    queue = _QUEUE
    if queue is None or _STOPPING or item.generation != _GENERATION:
        _finish_queue_item(item, error=RuntimeError("send_queue stopped during retry"))
        return
    if item.future.cancelled():
        _finish_queue_item(item)
        return
    global _SEQ
    _SEQ += 1
    queue.put_nowait((api_send_priority(item.api), _SEQ, item))


def _schedule_queue_retry(item: SendQueueItem, delay: float) -> None:
    task = asyncio.create_task(_requeue_item_with_delay(item, delay), name="ingress_send_queue_retry")
    item.retry_task = task
    _RETRY_TASKS.add(task)
    task.add_done_callback(_RETRY_TASKS.discard)


def _cancel_item_retry_if_cancelled(item: SendQueueItem) -> None:
    if item.future.cancelled() and item.retry_task is not None:
        item.retry_task.cancel()


async def _execute_queue_item(item: SendQueueItem) -> None:
    global _ORIGINAL_CALL_API
    if item.completed:
        return
    if item.future.cancelled():
        _finish_queue_item(item)
        return
    if item.generation != _GENERATION or _STOPPING:
        _finish_queue_item(item, error=RuntimeError("send_queue stopped before send"))
        return
    if _ORIGINAL_CALL_API is None:
        _finish_queue_item(item, error=RuntimeError("send_queue original _call_api missing"))
        return
    bot_self_id = str(getattr(item.bot, "self_id", ""))
    cooldown_left = is_send_bot_in_risk_cooldown(bot_self_id)
    if cooldown_left > 0:
        _schedule_queue_retry(item, cooldown_left)
        return
    token = _BYPASS.set(True)
    try:
        await _rate_limit_wait(bot_self_id)
        if item.future.cancelled() or item.completed:
            _finish_queue_item(item)
            return
        result = await _ORIGINAL_CALL_API(item.adapter, item.bot, item.api, **item.data)
        if item.completed:
            return
        _STATS["sent"] += 1
        _finish_queue_item(item, result=result)
    except Exception as exc:
        if item.completed:
            return
        _STATS["errors"] += 1
        record_send_queue_error(item.api, exc)
        retryable = is_retryable_send_error(item.api, exc) or is_risk_limited_send_error(item.api, exc)
        if (
            retryable
            and item.attempt < send_queue_retry_max()
            and not item.future.done()
            and item.generation == _GENERATION
            and not _STOPPING
        ):
            item.attempt += 1
            delay = send_error_retry_delay_sec(item.api, exc, item.attempt)
            _STATS["retries"] += 1
            if is_risk_limited_send_error(item.api, exc):
                note_send_risk_failure(bot_self_id)
            log_rate_limited(
                logger,
                "warning",
                f"send_queue.retry.{item.api}",
                format_business_event(
                    "发送队列",
                    "重试",
                    bot=bot_self_id,
                    api=item.api,
                    attempt=item.attempt,
                    delay_sec=round(delay, 2),
                    error=exc,
                ),
            )
            _schedule_queue_retry(item, delay)
            return
        if is_risk_limited_send_error(item.api, exc):
            note_send_risk_failure(bot_self_id)
        ambiguous = is_ambiguous_send_timeout(exc)
        log_rate_limited(
            logger,
            "warning",
            f"send_queue.error.{item.api}",
            format_business_event(
                "发送队列",
                "可能已投递" if ambiguous else "失败",
                bot=bot_self_id,
                api=item.api,
                error=exc,
            ),
        )
        _finish_queue_item(item, error=exc)
    except asyncio.CancelledError:
        _finish_queue_item(item, error=RuntimeError("send_queue stopped during send"))
        raise
    finally:
        _BYPASS.reset(token)


async def _send_queue_worker(_worker_id: int) -> None:
    queue = _QUEUE
    if queue is None:
        return
    while True:
        _priority, _seq, item = await queue.get()
        try:
            await _execute_queue_item(item)
        finally:
            queue.task_done()


async def enqueue_call_api(adapter: Any, bot: Any, api: str, **data: Any) -> Any:
    global _SEQ
    queue = _QUEUE
    changed = _CAPACITY_CHANGED
    generation = _GENERATION
    if queue is None or changed is None or _STOPPING:
        raise RuntimeError("send_queue not started")

    max_depth = send_queue_max_depth()
    depth = _STATS["depth"]
    if is_droppable_api(api) and depth >= max(1, max_depth // 2):
        _STATS["dropped"] += 1
        log_rate_limited(
            logger,
            "warning",
            "send_queue.drop.half",
            "Send queue dropped [{}] (depth [{}] >= [{}]/2), message not sent",
            api,
            depth,
            max_depth,
        )
        return None

    if api not in _HIGH_PRIORITY_APIS and depth >= max_depth:
        _STATS["dropped"] += 1
        log_rate_limited(
            logger,
            "warning",
            "send_queue.drop.full",
            "Send queue full, dropped [{}] (depth [{}] >= [{}]), message not sent",
            api,
            depth,
            max_depth,
        )
        return None

    if api in _HIGH_PRIORITY_APIS:
        deadline = asyncio.get_running_loop().time() + send_queue_enqueue_timeout_sec()
        while _STATS["depth"] >= max_depth:
            if _QUEUE is not queue or _GENERATION != generation or _STOPPING:
                raise RuntimeError("send_queue stopped while waiting for capacity")
            changed.clear()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                _STATS["dropped"] += 1
                raise TimeoutError("send_queue enqueue timed out")
            try:
                await asyncio.wait_for(changed.wait(), timeout=remaining)
            except TimeoutError as exc:
                _STATS["dropped"] += 1
                raise TimeoutError("send_queue enqueue timed out") from exc
        if _QUEUE is not queue or _GENERATION != generation or _STOPPING:
            raise RuntimeError("send_queue stopped while waiting for capacity")

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    item = SendQueueItem(adapter, bot, api, dict(data), future, generation=generation)
    future.add_done_callback(lambda _future: _cancel_item_retry_if_cancelled(item))
    _SEQ += 1
    _ACTIVE_ITEMS.add(item)
    _STATS["enqueued"] += 1
    _STATS["depth"] += 1
    queue.put_nowait((api_send_priority(api), _SEQ, item))

    from pallas.core.platform.ingress.message_load import record_send_queue_pressure

    record_send_queue_pressure(_STATS["depth"], max_depth)
    return await future


async def patched_call_api(adapter: Any, bot: Any, api: str, **data: Any) -> Any:
    if _BYPASS.get() or not send_queue_enabled() or not should_queue_api(api):
        assert _ORIGINAL_CALL_API is not None
        return await _ORIGINAL_CALL_API(adapter, bot, api, **data)
    return await enqueue_call_api(adapter, bot, api, **data)


async def start_send_queue_workers() -> None:
    global _QUEUE, _WORKERS, _CAPACITY_CHANGED, _STOP_COMPLETE, _GENERATION, _STOPPING
    if _QUEUE is not None:
        return
    if _STOPPING:
        raise RuntimeError("send_queue is stopping")
    _GENERATION += 1
    _STOPPING = False
    _CAPACITY_CHANGED = asyncio.Event()
    _STOP_COMPLETE = asyncio.Event()
    _QUEUE = asyncio.PriorityQueue(maxsize=0)
    worker_count = send_queue_worker_count()
    _WORKERS = [
        asyncio.create_task(_send_queue_worker(idx), name=f"ingress_send_queue_{idx}") for idx in range(worker_count)
    ]


async def _finish_send_queue_stop(
    queue: asyncio.PriorityQueue[tuple[int, int, SendQueueItem]] | None,
    tasks: list[asyncio.Task[None]],
    retry_tasks: list[asyncio.Task[None]],
    complete: asyncio.Event,
) -> None:
    global _STOPPING, _STOP_TASK
    try:
        for task in (*tasks, *retry_tasks):
            task.cancel()
        if tasks or retry_tasks:
            await asyncio.gather(*tasks, *retry_tasks, return_exceptions=True)
        if queue is not None:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                else:
                    queue.task_done()
            await queue.join()
    finally:
        _STOPPING = False
        complete.set()
        _STOP_TASK = None


async def stop_send_queue_workers() -> None:
    global _QUEUE, _WORKERS, _CAPACITY_CHANGED, _GENERATION, _STOPPING, _STOP_COMPLETE, _STOP_TASK
    if _STOPPING:
        if _STOP_TASK is not None:
            await asyncio.shield(_STOP_TASK)
        elif _STOP_COMPLETE is not None:
            await _STOP_COMPLETE.wait()
        return
    queue = _QUEUE
    changed = _CAPACITY_CHANGED
    tasks = list(_WORKERS)
    retry_tasks = list(_RETRY_TASKS)
    if queue is None and not tasks and not retry_tasks and not _ACTIVE_ITEMS:
        return
    _STOPPING = True
    _GENERATION += 1
    _QUEUE = None
    _WORKERS = []
    _CAPACITY_CHANGED = None
    if changed is not None:
        changed.set()
    for item in tuple(_ACTIVE_ITEMS):
        _finish_queue_item(item, error=RuntimeError("send_queue stopped"))
    complete = _STOP_COMPLETE
    if complete is None:
        complete = _STOP_COMPLETE = asyncio.Event()
    _STOP_TASK = asyncio.create_task(
        _finish_send_queue_stop(queue, tasks, retry_tasks, complete),
        name="ingress_send_queue_stop",
    )
    await asyncio.shield(_STOP_TASK)


def install_send_queue() -> None:
    global _PATCHED, _ORIGINAL_CALL_API
    if _PATCHED or not send_queue_enabled():
        return
    from nonebot.adapters.onebot.v11.adapter import Adapter

    _ORIGINAL_CALL_API = Adapter._call_api
    Adapter._call_api = patched_call_api  # type: ignore[method-assign,assignment]
    _PATCHED = True
    logger.debug(
        "Send queue initialized with [{}] workers, maximum depth [{}], and minimum interval [{}]ms.",
        send_queue_worker_count(),
        send_queue_max_depth(),
        send_queue_min_interval_sec() * 1000.0,
    )


def uninstall_send_queue() -> None:
    global _PATCHED, _ORIGINAL_CALL_API
    if not _PATCHED or _ORIGINAL_CALL_API is None:
        return
    from nonebot.adapters.onebot.v11.adapter import Adapter

    Adapter._call_api = _ORIGINAL_CALL_API  # type: ignore[method-assign,assignment]
    _PATCHED = False
    _ORIGINAL_CALL_API = None


def send_queue_installed() -> bool:
    return _PATCHED
