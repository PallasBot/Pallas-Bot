"""PostgreSQL 持久化后台任务队列。"""

from __future__ import annotations

import time

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .models import WorkJob


class PostgresWorkJobStore:
    async def enqueue(self, job: WorkJob) -> WorkJob:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session() as session:
            stmt = (
                pg_insert(BackgroundJobRow)
                .values(
                    id=job.id,
                    kind=job.kind,
                    payload=job.payload,
                    idempotency_key=job.idempotency_key,
                    status="pending",
                    attempts=job.attempts,
                    available_at=job.created_at,
                    created_at=job.created_at,
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
            )
            await session.execute(stmt)
            row = (
                await session.execute(
                    select(BackgroundJobRow).where(BackgroundJobRow.idempotency_key == job.idempotency_key)
                )
            ).scalar_one()
            await session.commit()
        return WorkJob(row.id, row.kind, dict(row.payload or {}), row.idempotency_key, row.created_at, row.attempts)

    async def claim(self, *, owner: str, lease_sec: float) -> WorkJob | None:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        now = time.time()
        async with get_session() as session:
            stmt = (
                select(BackgroundJobRow)
                .where(
                    BackgroundJobRow.finished_at.is_(None),
                    BackgroundJobRow.available_at <= now,
                    or_(BackgroundJobRow.status == "pending", BackgroundJobRow.leased_until < now),
                )
                .order_by(BackgroundJobRow.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            row.status = "leased"
            row.lease_owner = str(owner)
            row.leased_until = now + max(1.0, float(lease_sec))
            row.attempts += 1
            await session.commit()
        return WorkJob(row.id, row.kind, dict(row.payload or {}), row.idempotency_key, row.created_at, row.attempts)

    async def complete(self, *, job_id: str, owner: str) -> bool:
        return await self._release(job_id=job_id, owner=owner, completed=True, retry_after_sec=0)

    async def fail(self, *, job_id: str, owner: str, retry_after_sec: float) -> bool:
        return await self._release(job_id=job_id, owner=owner, completed=False, retry_after_sec=retry_after_sec)

    async def _release(self, *, job_id: str, owner: str, completed: bool, retry_after_sec: float) -> bool:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        now = time.time()
        values = {
            "status": "done" if completed else "pending",
            "lease_owner": None,
            "leased_until": None,
            "finished_at": now if completed else None,
            "available_at": now + max(0.0, retry_after_sec),
        }
        async with get_session() as session:
            result = await session.execute(
                update(BackgroundJobRow)
                .where(BackgroundJobRow.id == job_id, BackgroundJobRow.lease_owner == owner)
                .values(**values)
            )
            await session.commit()
        return bool(result.rowcount)
