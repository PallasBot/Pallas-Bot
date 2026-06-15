from __future__ import annotations

import asyncio
import contextvars
import time
from dataclasses import dataclass
from typing import Any

from nonebot.log import logger

from src.foundation.config.repo_settings import repo_env_raw_value

_ORIGINAL_CALL_API = None
_PATCHED = False
_BYPASS = contextvars.ContextVar("_ingress_send_queue_bypass", default=False)

_QUEUE: asyncio.PriorityQueue[tuple[int, int, SendQueueItem]] | None = None
_WORKERS: list[asyncio.Task[None]] = []
_SEQ = 0
_STATS = {
    "enqueued": 0,
    "sent": 0,
    "dropped": 0,
    "errors": 0,
    "depth": 0,
}
_LAST_SEND_AT: dict[str, float] = {}

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


@dataclass(slots=True)
class SendQueueItem:
    adapter: Any
    bot: Any
    api: str
    data: dict[str, Any]
    future: asyncio.Future[Any]


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


def api_send_priority(api: str) -> int:
    if api in _HIGH_PRIORITY_APIS:
        return 0
    return 10


def should_queue_api(api: str) -> bool:
    return api in _QUEUED_APIS


def is_droppable_api(api: str) -> bool:
    return api in _DROPPABLE_APIS


def send_queue_status() -> dict[str, Any]:
    queue = _QUEUE
    depth = queue.qsize() if queue is not None else 0
    return {
        "enabled": send_queue_enabled(),
        "installed": _PATCHED,
        "depth": depth,
        "max_depth": send_queue_max_depth(),
        "workers": send_queue_worker_count(),
        "min_interval_ms": send_queue_min_interval_sec() * 1000.0,
        **dict(_STATS),
        "depth_live": depth,
    }


def reset_send_queue_for_tests() -> None:
    global _SEQ, _PATCHED, _ORIGINAL_CALL_API
    _SEQ = 0
    _PATCHED = False
    _ORIGINAL_CALL_API = None
    for key in _STATS:
        _STATS[key] = 0
    _LAST_SEND_AT.clear()


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


async def _execute_queue_item(item: SendQueueItem) -> None:
    global _ORIGINAL_CALL_API
    if _ORIGINAL_CALL_API is None:
        item.future.set_exception(RuntimeError("send_queue original _call_api missing"))
        return
    token = _BYPASS.set(True)
    try:
        await _rate_limit_wait(str(getattr(item.bot, "self_id", "")))
        result = await _ORIGINAL_CALL_API(item.adapter, item.bot, item.api, **item.data)
        _STATS["sent"] += 1
        if not item.future.done():
            item.future.set_result(result)
    except Exception as exc:
        _STATS["errors"] += 1
        if not item.future.done():
            item.future.set_exception(exc)
    finally:
        _BYPASS.reset(token)
        _STATS["depth"] = max(0, _STATS["depth"] - 1)


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
    if queue is None:
        raise RuntimeError("send_queue not started")

    max_depth = send_queue_max_depth()
    depth = _STATS["depth"]
    if is_droppable_api(api) and depth >= max(1, max_depth // 2):
        _STATS["dropped"] += 1
        return None

    if depth >= max_depth and api not in _HIGH_PRIORITY_APIS:
        _STATS["dropped"] += 1
        return None

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    item = SendQueueItem(adapter, bot, api, dict(data), future)
    _SEQ += 1
    _STATS["enqueued"] += 1
    _STATS["depth"] += 1

    try:
        await asyncio.wait_for(
            queue.put((api_send_priority(api), _SEQ, item)),
            timeout=send_queue_enqueue_timeout_sec(),
        )
    except TimeoutError:
        _STATS["depth"] = max(0, _STATS["depth"] - 1)
        _STATS["dropped"] += 1
        if is_droppable_api(api):
            return None
        raise

    from src.platform.ingress.message_load import record_send_queue_pressure

    record_send_queue_pressure(_STATS["depth"], max_depth)
    return await future


async def patched_call_api(adapter: Any, bot: Any, api: str, **data: Any) -> Any:
    if _BYPASS.get() or not send_queue_enabled() or not should_queue_api(api):
        assert _ORIGINAL_CALL_API is not None
        return await _ORIGINAL_CALL_API(adapter, bot, api, **data)
    return await enqueue_call_api(adapter, bot, api, **data)


async def start_send_queue_workers() -> None:
    global _QUEUE, _WORKERS
    if _QUEUE is not None:
        return
    _QUEUE = asyncio.PriorityQueue(maxsize=0)
    worker_count = send_queue_worker_count()
    _WORKERS = [
        asyncio.create_task(_send_queue_worker(idx), name=f"ingress_send_queue_{idx}") for idx in range(worker_count)
    ]


async def stop_send_queue_workers() -> None:
    global _QUEUE, _WORKERS
    tasks = list(_WORKERS)
    _WORKERS = []
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _QUEUE = None


def install_send_queue() -> None:
    global _PATCHED, _ORIGINAL_CALL_API
    if _PATCHED or not send_queue_enabled():
        return
    from nonebot.adapters.onebot.v11.adapter import Adapter

    _ORIGINAL_CALL_API = Adapter._call_api
    Adapter._call_api = patched_call_api  # type: ignore[method-assign,assignment]
    _PATCHED = True
    logger.info(
        "send_queue: installed workers={} max_depth={} min_interval_ms={}",
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
