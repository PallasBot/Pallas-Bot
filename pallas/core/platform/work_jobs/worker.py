"""后台任务 worker 的通用领取与确认循环。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from nonebot import logger

from .observability import WorkAuxRuntimeMetrics

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
        max_attempts: int = 8,
        metrics: WorkAuxRuntimeMetrics | None = None,
    ) -> None:
        self.store = store
        self.owner = str(owner)
        self.handlers = dict(handlers)
        self.lease_sec = max(1.0, float(lease_sec))
        self.retry_after_sec = max(0.0, float(retry_after_sec))
        self.batch_size = max(1, int(batch_size))
        self.max_attempts = max(1, int(max_attempts))
        self.metrics = metrics or WorkAuxRuntimeMetrics()

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
                completed_jobs = [tasks[task] for task in completed_tasks if task.result()]
                for task in completed_tasks:
                    tasks.pop(task)
                if len(completed_jobs) != len(completed):
                    refill_slots = False
                if completed_jobs:
                    self.metrics.record_completed(await self.store.complete_many(jobs=completed_jobs, owner=self.owner))
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
            await self._fail_or_dead_letter(job, f"unknown job kind: {job.kind}")
            return None
        lease_task = asyncio.create_task(self._renew_lease(job), name=f"work_job_lease:{job.id}")
        handler_task = asyncio.create_task(handler(job.payload), name=f"work_job_handler:{job.id}")
        try:
            done, _ = await asyncio.wait((handler_task, lease_task), return_when=asyncio.FIRST_COMPLETED)
            if lease_task in done:
                handler_task.cancel()
                await asyncio.gather(handler_task, return_exceptions=True)
                self.metrics.record_failed()
                if await self.store.fail(
                    job_id=job.id,
                    owner=self.owner,
                    lease_id=job.lease_id or "",
                    retry_after_sec=self.retry_after_sec,
                ):
                    self.metrics.record_retried()
                return None
            await handler_task
        except Exception as exc:
            logger.warning("work aux: job failed kind={} id={}: {}", job.kind, job.id, exc)
            self.metrics.record_failed()
            await self._fail_or_dead_letter(job, str(exc))
            return None
        finally:
            if not handler_task.done():
                handler_task.cancel()
                await asyncio.gather(handler_task, return_exceptions=True)
            lease_task.cancel()
            await asyncio.gather(lease_task, return_exceptions=True)
        return job.id

    async def _fail_or_dead_letter(self, job, reason: str) -> None:
        if job.attempts >= self.max_attempts:
            dead_lettered = await self.store.dead_letter(
                job_id=job.id,
                owner=self.owner,
                lease_id=job.lease_id or "",
                reason=reason,
            )
            if dead_lettered:
                self.metrics.record_dead_lettered()
            return
        if await self.store.fail(
            job_id=job.id,
            owner=self.owner,
            lease_id=job.lease_id or "",
            retry_after_sec=self.retry_after_sec,
        ):
            self.metrics.record_retried()

    async def _renew_lease(self, job) -> None:
        while True:
            await asyncio.sleep(self.lease_sec / 3)
            if await self.store.renew(
                job_id=job.id,
                owner=self.owner,
                lease_id=job.lease_id or "",
                lease_sec=self.lease_sec,
            ):
                continue
            logger.warning("work aux: lease lost id={} owner={}", job.id, self.owner)
            return
