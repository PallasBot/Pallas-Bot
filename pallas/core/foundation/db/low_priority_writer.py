"""非关键追加写队列：背压时丢最旧，数据库不健康时暂停刷写。"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from nonebot import logger

FlushBatch = Callable[[list[Any]], Awaitable[None]]


@dataclass
class LowPriorityWriter:
    name: str
    flush_batch: FlushBatch
    max_retain: int = 2048
    batch_size: int = 64
    flush_interval_sec: float = 5.0
    buffer: deque[Any] = field(default_factory=deque)
    dropped: int = 0
    flushed: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _task: asyncio.Task[None] | None = field(default=None, repr=False)
    _wake: asyncio.Event = field(default_factory=asyncio.Event)

    def enqueue(self, item: Any) -> bool:
        """入队；满则丢最旧。返回是否入队成功（含替换最旧）。"""
        if len(self.buffer) >= self.max_retain:
            self.buffer.popleft()
            self.dropped += 1
        self.buffer.append(item)
        self._wake.set()
        return True

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "queued": len(self.buffer),
            "dropped": self.dropped,
            "flushed": self.flushed,
            "max_retain": self.max_retain,
        }

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name=f"lpw_{self.name}")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.flush_interval_sec)
            except TimeoutError:
                pass
            self._wake.clear()
            await self._flush_once()

    async def _flush_once(self) -> None:
        from pallas.core.foundation.db.db_health import should_skip_noncritical_db

        if should_skip_noncritical_db():
            return
        async with self._lock:
            if not self.buffer:
                return
            batch: list[Any] = []
            while self.buffer and len(batch) < self.batch_size:
                batch.append(self.buffer.popleft())
        if not batch:
            return
        try:
            await self.flush_batch(batch)
            self.flushed += len(batch)
        except Exception as e:  # noqa: BLE001
            logger.warning("low_priority_writer {} flush failed: {}", self.name, e)
            # 失败项重新入队尾部，避免静默丢数；满时仍可能被后续背压丢掉
            async with self._lock:
                for item in reversed(batch):
                    if len(self.buffer) >= self.max_retain:
                        self.buffer.popleft()
                        self.dropped += 1
                    self.buffer.appendleft(item)


_writers: dict[str, LowPriorityWriter] = {}


def get_or_create_low_priority_writer(
    name: str,
    flush_batch: FlushBatch,
    *,
    max_retain: int = 2048,
    batch_size: int = 64,
) -> LowPriorityWriter:
    existing = _writers.get(name)
    if existing is not None:
        return existing
    writer = LowPriorityWriter(
        name=name,
        flush_batch=flush_batch,
        max_retain=max_retain,
        batch_size=batch_size,
    )
    _writers[name] = writer
    writer.start()
    return writer


def low_priority_writers_snapshot() -> list[dict[str, Any]]:
    return [w.snapshot() for w in _writers.values()]


async def reset_low_priority_writers_for_tests() -> None:
    for w in list(_writers.values()):
        await w.stop()
    _writers.clear()
