"""后台任务 worker 的通用领取与确认循环。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from nonebot import logger

if TYPE_CHECKING:
    from .store import WorkJobStore

WorkJobHandler = Callable[[dict[str, Any]], Awaitable[None]]


class WorkJobWorker:
    def __init__(
        self,
        *,
        store: WorkJobStore,
        owner: str,
        handlers: dict[str, WorkJobHandler],
        lease_sec: float = 60.0,
        retry_after_sec: float = 5.0,
    ) -> None:
        self.store = store
        self.owner = str(owner)
        self.handlers = dict(handlers)
        self.lease_sec = max(1.0, float(lease_sec))
        self.retry_after_sec = max(0.0, float(retry_after_sec))

    async def run_once(self) -> bool:
        job = await self.store.claim(owner=self.owner, lease_sec=self.lease_sec)
        if job is None:
            return False
        handler = self.handlers.get(job.kind)
        if handler is None:
            logger.error("work aux: unknown job kind={} id={}", job.kind, job.id)
            await self.store.complete(job_id=job.id, owner=self.owner)
            return True
        lease_task = asyncio.create_task(self._renew_lease(job.id), name=f"work_job_lease:{job.id}")
        try:
            await handler(job.payload)
        except Exception as exc:
            logger.warning("work aux: job failed kind={} id={}: {}", job.kind, job.id, exc)
            await self.store.fail(job_id=job.id, owner=self.owner, retry_after_sec=self.retry_after_sec)
            return True
        finally:
            lease_task.cancel()
            await asyncio.gather(lease_task, return_exceptions=True)
        await self.store.complete(job_id=job.id, owner=self.owner)
        return True

    async def _renew_lease(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self.lease_sec / 3)
            if await self.store.renew(job_id=job_id, owner=self.owner, lease_sec=self.lease_sec):
                continue
            logger.warning("work aux: lease lost id={} owner={}", job_id, self.owner)
            return
