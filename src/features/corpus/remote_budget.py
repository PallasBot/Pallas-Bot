"""社区语料远程 HTTP 并发与池背压。"""

from __future__ import annotations

import asyncio

from src.foundation.db.pool_budget import pg_pool_under_pressure, remote_corpus_concurrency_limit

_remote_sem: asyncio.Semaphore | None = None
_remote_sem_limit: int | None = None
_skipped_pressure: int = 0
_skipped_busy: int = 0


def clear_remote_corpus_budget_state() -> None:
    global _remote_sem, _remote_sem_limit
    _remote_sem = None
    _remote_sem_limit = None


def remote_corpus_sem() -> asyncio.Semaphore:
    global _remote_sem, _remote_sem_limit
    limit = remote_corpus_concurrency_limit()
    if _remote_sem is None or _remote_sem_limit != limit:
        _remote_sem = asyncio.Semaphore(limit)
        _remote_sem_limit = limit
    return _remote_sem


def remote_corpus_budget_snapshot() -> dict[str, int]:
    return {
        "skipped_pressure": _skipped_pressure,
        "skipped_busy": _skipped_busy,
        "limit": remote_corpus_concurrency_limit(),
    }


def drain_remote_corpus_skip_counters() -> dict[str, int]:
    global _skipped_pressure, _skipped_busy
    snap = {
        "skipped_pressure": _skipped_pressure,
        "skipped_busy": _skipped_busy,
        "limit": remote_corpus_concurrency_limit(),
    }
    _skipped_pressure = 0
    _skipped_busy = 0
    return snap


def should_skip_remote_corpus(*, hot_path: bool = False) -> bool:
    """池压力大时跳过远程语料。"""
    global _skipped_pressure
    threshold = 0.70 if hot_path else 0.55
    if pg_pool_under_pressure(threshold=threshold):
        _skipped_pressure += 1
        return True
    return False


class _RemoteCorpusSlot:
    __slots__ = ("acquired",)

    def __init__(self) -> None:
        self.acquired = False


async def try_remote_corpus_slot(*, wait: bool = True) -> _RemoteCorpusSlot | None:
    """获取远程语料并发槽；池满或槽满时可立即放弃。"""
    global _skipped_busy
    if should_skip_remote_corpus(hot_path=False):
        return None
    sem = remote_corpus_sem()
    if wait:
        await sem.acquire()
        slot = _RemoteCorpusSlot()
        slot.acquired = True
        return slot
    try:
        await asyncio.wait_for(sem.acquire(), timeout=0)
    except TimeoutError:
        _skipped_busy += 1
        return None
    slot = _RemoteCorpusSlot()
    slot.acquired = True
    return slot


def release_remote_corpus_slot(slot: _RemoteCorpusSlot | None) -> None:
    if slot is None or not slot.acquired:
        return
    remote_corpus_sem().release()
    slot.acquired = False


class RemoteCorpusBudget:
    """async with 包裹远程 find/contribute。"""

    def __init__(self, *, hot_path: bool = False, wait: bool = True) -> None:
        self._hot_path = hot_path
        self._wait = wait
        self._slot: _RemoteCorpusSlot | None = None
        self.skipped = False

    async def __aenter__(self) -> RemoteCorpusBudget:
        if should_skip_remote_corpus(hot_path=self._hot_path):
            self.skipped = True
            return self
        sem = remote_corpus_sem()
        if self._wait:
            await sem.acquire()
            self._slot = _RemoteCorpusSlot()
            self._slot.acquired = True
        else:
            try:
                await asyncio.wait_for(sem.acquire(), timeout=0)
            except TimeoutError:
                global _skipped_busy
                _skipped_busy += 1
                self.skipped = True
                return self
            self._slot = _RemoteCorpusSlot()
            self._slot.acquired = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        release_remote_corpus_slot(self._slot)
        self._slot = None
