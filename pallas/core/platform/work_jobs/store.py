"""后台任务存储抽象；测试可用内存实现验证租约语义。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .models import WorkJob


class WorkJobStore(Protocol):
    async def enqueue(self, job: WorkJob) -> WorkJob: ...

    async def enqueue_many(self, jobs: list[WorkJob]) -> list[WorkJob]: ...

    async def claim(self, *, owner: str, lease_sec: float) -> WorkJob | None: ...

    async def claim_many(self, *, owner: str, lease_sec: float, limit: int) -> list[WorkJob]: ...

    async def renew(self, *, job_id: str, owner: str, lease_sec: float) -> bool: ...

    async def complete(self, *, job_id: str, owner: str) -> bool: ...

    async def complete_many(self, *, job_ids: list[str], owner: str) -> int: ...

    async def fail(self, *, job_id: str, owner: str, retry_after_sec: float) -> bool: ...

    async def stats(self) -> dict[str, float | int | None]: ...


class MemoryWorkJobStore:
    """仅用于测试和不可用时的显式降级，不作为生产持久化队列。"""

    def __init__(self) -> None:
        self._jobs: dict[str, WorkJob] = {}
        self._idempotency: dict[str, str] = {}
        self._available_at: dict[str, float] = {}
        self._enqueued_at: dict[str, float] = {}
        self._leases: dict[str, tuple[str, float]] = {}
        self._completed: set[str] = set()
        self._lock = asyncio.Lock()

    async def enqueue(self, job: WorkJob) -> WorkJob:
        async with self._lock:
            existing_id = self._idempotency.get(job.idempotency_key)
            if existing_id is not None:
                return self._jobs[existing_id]
            self._jobs[job.id] = job
            self._idempotency[job.idempotency_key] = job.id
            self._available_at[job.id] = time.monotonic()
            self._enqueued_at[job.id] = time.monotonic()
            return job

    async def enqueue_many(self, jobs: list[WorkJob]) -> list[WorkJob]:
        return [await self.enqueue(job) for job in jobs]

    async def claim(self, *, owner: str, lease_sec: float) -> WorkJob | None:
        now = time.monotonic()
        async with self._lock:
            for job_id, job in self._jobs.items():
                if job_id in self._completed or self._available_at.get(job_id, 0.0) > now:
                    continue
                lease = self._leases.get(job_id)
                if lease is not None and lease[1] > now:
                    continue
                claimed = replace(job, attempts=job.attempts + 1)
                self._jobs[job_id] = claimed
                self._leases[job_id] = (str(owner), now + max(0.01, float(lease_sec)))
                return claimed
        return None

    async def claim_many(self, *, owner: str, lease_sec: float, limit: int) -> list[WorkJob]:
        now = time.monotonic()
        claimed: list[WorkJob] = []
        async with self._lock:
            for job_id, job in self._jobs.items():
                if len(claimed) >= max(1, int(limit)):
                    break
                if job_id in self._completed or self._available_at.get(job_id, 0.0) > now:
                    continue
                lease = self._leases.get(job_id)
                if lease is not None and lease[1] > now:
                    continue
                item = replace(job, attempts=job.attempts + 1)
                self._jobs[job_id] = item
                self._leases[job_id] = (str(owner), now + max(0.01, float(lease_sec)))
                claimed.append(item)
        return claimed

    async def renew(self, *, job_id: str, owner: str, lease_sec: float) -> bool:
        now = time.monotonic()
        async with self._lock:
            lease = self._leases.get(job_id)
            if lease is None or lease[0] != owner or lease[1] <= now:
                return False
            self._leases[job_id] = (str(owner), now + max(0.01, float(lease_sec)))
            return True

    async def complete(self, *, job_id: str, owner: str) -> bool:
        async with self._lock:
            lease = self._leases.get(job_id)
            if lease is None or lease[0] != owner:
                return False
            self._completed.add(job_id)
            self._leases.pop(job_id, None)
            return True

    async def complete_many(self, *, job_ids: list[str], owner: str) -> int:
        completed = 0
        async with self._lock:
            for job_id in job_ids:
                lease = self._leases.get(job_id)
                if lease is None or lease[0] != owner:
                    continue
                self._completed.add(job_id)
                self._leases.pop(job_id, None)
                completed += 1
        return completed

    async def fail(self, *, job_id: str, owner: str, retry_after_sec: float) -> bool:
        async with self._lock:
            lease = self._leases.get(job_id)
            if lease is None or lease[0] != owner:
                return False
            self._leases.pop(job_id, None)
            self._available_at[job_id] = time.monotonic() + max(0.0, float(retry_after_sec))
            return True

    async def stats(self) -> dict[str, float | int | None]:
        now = time.monotonic()
        async with self._lock:
            pending = [
                job
                for job_id, job in self._jobs.items()
                if job_id not in self._completed and job_id not in self._leases
            ]
            leased = [
                job
                for job_id, job in self._jobs.items()
                if job_id not in self._completed and job_id in self._leases and self._leases[job_id][1] > now
            ]
            oldest_created = min((self._enqueued_at[job.id] for job in pending), default=None)
            return {
                "pending": len(pending),
                "leased": len(leased),
                "oldest_pending_age_sec": round(now - oldest_created, 3) if oldest_created is not None else None,
                "max_attempts": max((job.attempts for job in self._jobs.values()), default=0),
            }
