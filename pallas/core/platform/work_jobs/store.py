"""后台任务存储抽象；测试可用内存实现验证租约语义。"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .models import WorkJob


class WorkJobStore(Protocol):
    async def enqueue(self, job: WorkJob) -> WorkJob: ...

    async def requeue_terminal(self, job: WorkJob) -> tuple[WorkJob, bool]: ...

    async def enqueue_many(self, jobs: list[WorkJob]) -> list[WorkJob]: ...

    async def claim(
        self,
        *,
        owner: str,
        lease_sec: float,
        kinds: frozenset[str] | None = None,
        exclude_kinds: frozenset[str] | None = None,
        bot_owner_ids: frozenset[int] | None = None,
        priority_kinds: frozenset[str] | None = None,
    ) -> WorkJob | None: ...

    async def claim_many(
        self,
        *,
        owner: str,
        lease_sec: float,
        limit: int,
        kinds: frozenset[str] | None = None,
        exclude_kinds: frozenset[str] | None = None,
        bot_owner_ids: frozenset[int] | None = None,
        priority_kinds: frozenset[str] | None = None,
    ) -> list[WorkJob]: ...

    async def renew(self, *, job_id: str, owner: str, lease_id: str, lease_sec: float) -> bool: ...

    async def complete(self, *, job_id: str, owner: str, lease_id: str) -> bool: ...

    async def complete_many(self, *, jobs: list[WorkJob], owner: str) -> int: ...

    async def fail(self, *, job_id: str, owner: str, lease_id: str, retry_after_sec: float) -> bool: ...

    async def dead_letter(self, *, job_id: str, owner: str, lease_id: str, reason: str) -> bool: ...

    async def stats(self) -> dict[str, float | int | None]: ...


class MemoryWorkJobStore:
    """仅用于测试和不可用时的显式降级，不作为生产持久化队列。"""

    def __init__(self, *, completion_retention: Mapping[str, str] | None = None) -> None:
        self._jobs: dict[str, WorkJob] = {}
        self._idempotency: dict[str, str] = {}
        self._available_at: dict[str, float] = {}
        self._enqueued_at: dict[str, float] = {}
        self._leases: dict[str, tuple[str, float, str]] = {}
        self._completed: set[str] = set()
        self._dead_lettered: set[str] = set()
        self._retained: set[str] = set()
        self._completion_retention: Mapping[str, str] = completion_retention or {}
        self._lock = asyncio.Lock()

    def _retain_or_complete(self, job_id: str, job: WorkJob) -> None:
        """完成命中映射的kind：保留并打上终态标记；未命中则记入_completed。"""
        status = self._completion_retention.get(job.kind)
        if status is not None:
            self._retained.add(job_id)
            return
        self._completed.add(job_id)

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

    async def requeue_terminal(self, job: WorkJob) -> tuple[WorkJob, bool]:
        async with self._lock:
            existing_id = self._idempotency.get(job.idempotency_key)
            if existing_id is None:
                self._jobs[job.id] = job
                self._idempotency[job.idempotency_key] = job.id
                self._available_at[job.id] = time.monotonic()
                self._enqueued_at[job.id] = time.monotonic()
                return job, True
            if existing_id in self._retained or (
                existing_id not in self._completed and existing_id not in self._dead_lettered
            ):
                return self._jobs[existing_id], False
            self._jobs.pop(existing_id, None)
            self._available_at.pop(existing_id, None)
            self._enqueued_at.pop(existing_id, None)
            self._completed.discard(existing_id)
            self._dead_lettered.discard(existing_id)
            self._jobs[job.id] = job
            self._idempotency[job.idempotency_key] = job.id
            self._available_at[job.id] = time.monotonic()
            self._enqueued_at[job.id] = time.monotonic()
            return job, True

    async def enqueue_many(self, jobs: list[WorkJob]) -> list[WorkJob]:
        return [await self.enqueue(job) for job in jobs]

    async def claim(
        self,
        *,
        owner: str,
        lease_sec: float,
        kinds: frozenset[str] | None = None,
        exclude_kinds: frozenset[str] | None = None,
        bot_owner_ids: frozenset[int] | None = None,
        priority_kinds: frozenset[str] | None = None,
    ) -> WorkJob | None:
        now = time.monotonic()
        async with self._lock:
            ordered = _sort_claimable_jobs(self._jobs, priority_kinds=priority_kinds)
            for job_id, job in ordered:
                if not _job_matches(job, kinds=kinds, exclude_kinds=exclude_kinds, bot_owner_ids=bot_owner_ids):
                    continue
                if (
                    job_id in self._completed
                    or job_id in self._retained
                    or job_id in self._dead_lettered
                    or self._available_at.get(job_id, 0.0) > now
                ):
                    continue
                lease = self._leases.get(job_id)
                if lease is not None and lease[1] > now:
                    continue
                claimed = replace(job, attempts=job.attempts + 1)
                self._jobs[job_id] = claimed
                lease_id = uuid.uuid4().hex
                self._leases[job_id] = (str(owner), now + max(0.01, float(lease_sec)), lease_id)
                return replace(claimed, lease_id=lease_id)
        return None

    async def claim_many(
        self,
        *,
        owner: str,
        lease_sec: float,
        limit: int,
        kinds: frozenset[str] | None = None,
        exclude_kinds: frozenset[str] | None = None,
        bot_owner_ids: frozenset[int] | None = None,
        priority_kinds: frozenset[str] | None = None,
    ) -> list[WorkJob]:
        now = time.monotonic()
        claimed: list[WorkJob] = []
        async with self._lock:
            ordered = _sort_claimable_jobs(self._jobs, priority_kinds=priority_kinds)
            for job_id, job in ordered:
                if len(claimed) >= max(1, int(limit)):
                    break
                if not _job_matches(job, kinds=kinds, exclude_kinds=exclude_kinds, bot_owner_ids=bot_owner_ids):
                    continue
                if (
                    job_id in self._completed
                    or job_id in self._retained
                    or job_id in self._dead_lettered
                    or self._available_at.get(job_id, 0.0) > now
                ):
                    continue
                lease = self._leases.get(job_id)
                if lease is not None and lease[1] > now:
                    continue
                item = replace(job, attempts=job.attempts + 1)
                self._jobs[job_id] = item
                lease_id = uuid.uuid4().hex
                self._leases[job_id] = (str(owner), now + max(0.01, float(lease_sec)), lease_id)
                claimed.append(replace(item, lease_id=lease_id))
        return claimed

    async def renew(self, *, job_id: str, owner: str, lease_id: str, lease_sec: float) -> bool:
        now = time.monotonic()
        async with self._lock:
            lease = self._leases.get(job_id)
            if lease is None or lease[0] != owner or lease[2] != lease_id or lease[1] <= now:
                return False
            self._leases[job_id] = (str(owner), now + max(0.01, float(lease_sec)), lease_id)
            return True

    async def complete(self, *, job_id: str, owner: str, lease_id: str) -> bool:
        async with self._lock:
            lease = self._leases.get(job_id)
            if lease is None or lease[0] != owner or lease[2] != lease_id:
                return False
            job = self._jobs.get(job_id)
            if job is not None:
                self._retain_or_complete(job_id, job)
            self._leases.pop(job_id, None)
            return True

    async def complete_many(self, *, jobs: list[WorkJob], owner: str) -> int:
        completed = 0
        async with self._lock:
            for job in jobs:
                job_id = job.id
                lease = self._leases.get(job_id)
                if lease is None or lease[0] != owner or lease[2] != job.lease_id:
                    continue
                current = self._jobs.get(job_id)
                if current is not None:
                    self._retain_or_complete(job_id, current)
                self._leases.pop(job_id, None)
                completed += 1
        return completed

    async def fail(self, *, job_id: str, owner: str, lease_id: str, retry_after_sec: float) -> bool:
        async with self._lock:
            lease = self._leases.get(job_id)
            if lease is None or lease[0] != owner or lease[2] != lease_id:
                return False
            self._leases.pop(job_id, None)
            self._available_at[job_id] = time.monotonic() + max(0.0, float(retry_after_sec))
            return True

    async def dead_letter(self, *, job_id: str, owner: str, lease_id: str, reason: str) -> bool:
        async with self._lock:
            lease = self._leases.get(job_id)
            if lease is None or lease[0] != owner or lease[2] != lease_id:
                return False
            self._leases.pop(job_id, None)
            self._dead_lettered.add(job_id)
            return True

    async def stats(self) -> dict[str, float | int | None]:
        now = time.monotonic()
        async with self._lock:
            pending = [
                job
                for job_id, job in self._jobs.items()
                if job_id not in self._completed and job_id not in self._retained and job_id not in self._leases
            ]
            leased = [
                job
                for job_id, job in self._jobs.items()
                if job_id not in self._completed
                and job_id not in self._retained
                and job_id in self._leases
                and self._leases[job_id][1] > now
            ]
            oldest_created = min((self._enqueued_at[job.id] for job in pending), default=None)
            return {
                "pending": len(pending),
                "leased": len(leased),
                "dead_lettered": len(self._dead_lettered),
                "oldest_pending_age_sec": round(now - oldest_created, 3) if oldest_created is not None else None,
                "max_attempts": max((job.attempts for job in self._jobs.values()), default=0),
            }


def _job_matches(
    job,
    *,
    kinds: frozenset[str] | None,
    exclude_kinds: frozenset[str] | None,
    bot_owner_ids: frozenset[int] | None,
) -> bool:
    if kinds is not None and job.kind not in kinds:
        return False
    if exclude_kinds is not None and job.kind in exclude_kinds:
        return False
    if bot_owner_ids is not None:
        raw = job.payload.get("bot_qq")
        try:
            owner = int(raw)
        except (TypeError, ValueError):
            return False
        if owner not in bot_owner_ids:
            return False
    return True


def _sort_claimable_jobs(jobs: dict[str, object], *, priority_kinds: frozenset[str] | None) -> list[tuple[str, object]]:
    ordered = list(jobs.items())
    if priority_kinds:
        ordered.sort(key=lambda item: (0 if item[1].kind in priority_kinds else 1, item[1].created_at))
    else:
        ordered.sort(key=lambda item: item[1].created_at)
    return ordered
