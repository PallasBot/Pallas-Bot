"""社区语料异步回填：接话热路径 local miss 后后台拉取并写入本地库。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nonebot import get_driver, logger

from src.features.corpus.config import remote_corpus_find_mode
from src.features.corpus.find_cache import invalidate_find_cache

if TYPE_CHECKING:
    from src.foundation.db.modules import Context

_prefetch_queue: asyncio.Queue[str] | None = None
_prefetch_tasks: list[asyncio.Task[None]] = []
_scheduled_keys: set[str] = set()
_recent_prefetch_until: dict[str, float] = {}
_recent_miss_state: dict[str, tuple[int, float]] = {}
_prefetch_dropped_full: int = 0
_prefetch_completed: int = 0
_QUEUE_MAX = 4096
_RECENT_PREFETCH_TTL_SEC = 90.0
_RECENT_PREFETCH_MAX = 50_000
_RECENT_MISS_TTL_SEC = 45.0
_RECENT_MISS_MAX = 20_000
_SHORT_KEY_REPEAT_LEN = 6
_SHORT_KEY_REPEAT_MISSES = 2
_LIFECYCLE_BOUND = False


def prefetch_queue() -> asyncio.Queue[str]:
    global _prefetch_queue
    if _prefetch_queue is None:
        _prefetch_queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    return _prefetch_queue


def clear_corpus_prefetch_runtime_state() -> None:
    global _prefetch_queue, _scheduled_keys, _recent_prefetch_until, _recent_miss_state
    _prefetch_queue = None
    _scheduled_keys.clear()
    _recent_prefetch_until.clear()
    _recent_miss_state.clear()


def prefetch_queue_pressure_threshold() -> int:
    return max(32, _QUEUE_MAX // 64)


def prefetch_queue_under_pressure() -> bool:
    return prefetch_queue().qsize() >= prefetch_queue_pressure_threshold()


def should_delay_prefetch_until_repeat(keywords: str, now: float | None = None) -> bool:
    key = (keywords or "").strip()
    if not key or len(key) > _SHORT_KEY_REPEAT_LEN:
        return False
    ts = time.monotonic() if now is None else now
    count, until = _recent_miss_state.get(key, (0, 0.0))
    if ts >= until:
        count = 0
    count += 1
    _recent_miss_state[key] = (count, ts + _RECENT_MISS_TTL_SEC)
    if len(_recent_miss_state) > _RECENT_MISS_MAX:
        stale = [k for k, (_, exp) in _recent_miss_state.items() if ts >= exp]
        for stale_key in stale:
            _recent_miss_state.pop(stale_key, None)
        if len(_recent_miss_state) > _RECENT_MISS_MAX:
            _recent_miss_state.clear()
    return count < _SHORT_KEY_REPEAT_MISSES


def should_skip_corpus_prefetch() -> bool:
    from src.foundation.db.pool_budget import pg_pool_under_pressure
    from src.plugins.repeater.learn_queue import learn_queue_under_pressure

    if pg_pool_under_pressure(threshold=0.15):
        return True
    if learn_queue_under_pressure():
        return True
    if prefetch_queue_under_pressure():
        return True
    return False


def schedule_corpus_prefetch(keywords: str) -> None:
    """接话 local miss 时调用；不阻塞热路径。"""
    if remote_corpus_find_mode() != "prefetch":
        return
    if should_skip_corpus_prefetch():
        return
    now = time.monotonic()
    key = (keywords or "").strip()
    if not key or key in _scheduled_keys:
        return
    if should_delay_prefetch_until_repeat(key, now):
        return
    until = _recent_prefetch_until.get(key)
    if until is not None:
        if now < until:
            return
        _recent_prefetch_until.pop(key, None)
    if len(_recent_prefetch_until) > _RECENT_PREFETCH_MAX:
        stale = [k for k, exp in _recent_prefetch_until.items() if now >= exp]
        for stale_key in stale:
            _recent_prefetch_until.pop(stale_key, None)
        if len(_recent_prefetch_until) > _RECENT_PREFETCH_MAX:
            _recent_prefetch_until.clear()
    try:
        prefetch_queue().put_nowait(key)
        _scheduled_keys.add(key)
    except asyncio.QueueFull:
        global _prefetch_dropped_full
        _prefetch_dropped_full += 1
        if _prefetch_dropped_full == 1 or _prefetch_dropped_full % 200 == 0:
            logger.debug(
                "corpus prefetch queue full (max={}), dropped={}",
                _QUEUE_MAX,
                _prefetch_dropped_full,
            )


async def import_remote_context_to_local(local, ctx: Context) -> bool:
    key = (ctx.keywords or "").strip()
    if not key or not ctx.answers:
        return False
    exists = await local.context_exists_by_keywords(key)
    if not exists:
        await local.insert(ctx)
        await invalidate_find_cache(key)
        return True
    for ans in ctx.answers:
        if not ans.messages:
            continue
        for msg in ans.messages:
            text = str(msg or "").strip()
            if not text:
                continue
            await local.upsert_answer(
                keywords=key,
                group_id=int(ans.group_id),
                answer_keywords=str(ans.keywords or ""),
                answer_time=int(ans.time),
                message=text,
                append_on_existing=True,
            )
    await invalidate_find_cache(key)
    return True


async def execute_corpus_prefetch(keywords: str) -> None:
    from src.features.corpus.factory import build_community_repository
    from src.features.corpus.remote_budget import should_skip_remote_corpus

    key = (keywords or "").strip()
    if not key:
        return
    if should_skip_remote_corpus(hot_path=False):
        return
    community = build_community_repository()
    if community is None:
        return
    from src.foundation.db.context_repo_access import get_shared_context_repository

    repo = get_shared_context_repository()
    local = getattr(repo, "_local", None)
    if local is None:
        return
    if await local.context_exists_by_keywords(key):
        find_reply = getattr(local, "find_by_keywords_for_reply", None)
        if callable(find_reply):
            local_ctx = await find_reply(key)
        else:
            local_ctx = await local.find_by_keywords(key)
        if local_ctx is not None and local_ctx.answers:
            return
    try:
        remote_ctx = await community.find_by_keywords(key)
    except Exception as e:
        logger.debug("corpus prefetch remote find failed keywords_len={}: {}", len(key), e)
        return
    if remote_ctx is None or not remote_ctx.answers:
        return
    try:
        await import_remote_context_to_local(local, remote_ctx)
        global _prefetch_completed
        _prefetch_completed += 1
    except Exception as e:
        logger.debug("corpus prefetch local import failed keywords_len={}: {}", len(key), e)


async def run_prefetch_consumer() -> None:
    while True:
        key = await prefetch_queue().get()
        try:
            await execute_corpus_prefetch(key)
        finally:
            _scheduled_keys.discard(key)
            _recent_prefetch_until[key] = time.monotonic() + _RECENT_PREFETCH_TTL_SEC
            prefetch_queue().task_done()


def prefetch_concurrency() -> int:
    from src.foundation.db.pool_budget import cap_by_pg_pool, remote_corpus_concurrency_limit

    return cap_by_pg_pool(remote_corpus_concurrency_limit(), workload_fraction=0.05)


async def start_corpus_prefetch_workers() -> None:
    global _prefetch_tasks
    if _prefetch_tasks and any(not t.done() for t in _prefetch_tasks):
        return
    await stop_corpus_prefetch_workers()
    n = prefetch_concurrency()
    _prefetch_tasks = [
        asyncio.create_task(run_prefetch_consumer(), name=f"corpus_prefetch_consumer_{i}") for i in range(n)
    ]
    logger.debug("corpus prefetch workers started: consumers={} queue_max={}", n, _QUEUE_MAX)


async def stop_corpus_prefetch_workers() -> None:
    global _prefetch_tasks
    if not _prefetch_tasks:
        return
    tasks = list(_prefetch_tasks)
    _prefetch_tasks = []
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def reload_corpus_prefetch_workers() -> None:
    clear_corpus_prefetch_runtime_state()
    await stop_corpus_prefetch_workers()
    if remote_corpus_find_mode() == "prefetch":
        await start_corpus_prefetch_workers()


def bind_corpus_prefetch_lifecycle() -> None:
    global _LIFECYCLE_BOUND
    if _LIFECYCLE_BOUND:
        return
    _LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        if remote_corpus_find_mode() == "prefetch":
            await start_corpus_prefetch_workers()

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        await stop_corpus_prefetch_workers()
