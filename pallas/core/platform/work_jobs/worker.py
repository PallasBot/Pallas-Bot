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
        batch_size: int = 1,
    ) -> None:
        self.store = store
        self.owner = str(owner)
        self.handlers = dict(handlers)
        self.lease_sec = max(1.0, float(lease_sec))
        self.retry_after_sec = max(0.0, float(retry_after_sec))
        self.batch_size = max(1, int(batch_size))

    async def run_once(self) -> bool:
        jobs = await self.store.claim_many(owner=self.owner, lease_sec=self.lease_sec, limit=self.batch_size)
        if not jobs:
            return False
        tasks = {asyncio.create_task(self._run_job(job)): job for job in jobs}
        refill_slots = True
        try:
            while tasks:
                completed_tasks, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                completed = [task.result() for task in completed_tasks]
                for task in completed_tasks:
                    tasks.pop(task)
                job_ids = [job_id for job_id in completed if job_id is not None]
                if len(job_ids) != len(completed):
                    refill_slots = False
                if job_ids:
                    await self.store.complete_many(job_ids=job_ids, owner=self.owner)
                available_slots = self.batch_size - len(tasks)
                if refill_slots and available_slots > 0:
                    next_jobs = await self.store.claim_many(
                        owner=self.owner,
                        lease_sec=self.lease_sec,
                        limit=available_slots,
                    )
                    tasks.update({asyncio.create_task(self._run_job(job)): job for job in next_jobs})
            return True
        finally:
            if tasks:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_job(self, job) -> str | None:
        handler = self.handlers.get(job.kind)
        if handler is None:
            logger.error("work aux: unknown job kind={} id={}", job.kind, job.id)
            return job.id
        lease_task = asyncio.create_task(self._renew_lease(job.id), name=f"work_job_lease:{job.id}")
        try:
            await handler(job.payload)
        except Exception as exc:
            logger.warning("work aux: job failed kind={} id={}: {}", job.kind, job.id, exc)
            await self.store.fail(job_id=job.id, owner=self.owner, retry_after_sec=self.retry_after_sec)
            return None
        finally:
            lease_task.cancel()
            await asyncio.gather(lease_task, return_exceptions=True)
        return job.id

    async def _renew_lease(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self.lease_sec / 3)
            if await self.store.renew(job_id=job_id, owner=self.owner, lease_sec=self.lease_sec):
                continue
            logger.warning("work aux: lease lost id={} owner={}", job_id, self.owner)
            return
