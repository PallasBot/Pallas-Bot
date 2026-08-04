"""PostgreSQL 持久化后台任务队列。"""

from __future__ import annotations

import time

from sqlalchemy import func, or_, select, update
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

    async def enqueue_many(self, jobs: list[WorkJob]) -> list[WorkJob]:
        if not jobs:
            return []
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        keys = [job.idempotency_key for job in jobs]
        values = [
            {
                "id": job.id,
                "kind": job.kind,
                "payload": job.payload,
                "idempotency_key": job.idempotency_key,
                "status": "pending",
                "attempts": job.attempts,
                "available_at": job.created_at,
                "created_at": job.created_at,
            }
            for job in jobs
        ]
        async with get_session() as session:
            stmt = pg_insert(BackgroundJobRow).values(values).on_conflict_do_nothing(index_elements=["idempotency_key"])
            await session.execute(stmt)
            rows = (
                await session.execute(select(BackgroundJobRow).where(BackgroundJobRow.idempotency_key.in_(keys)))
            ).scalars()
            by_key = {row.idempotency_key: row for row in rows}
            await session.commit()
        return [
            WorkJob(row.id, row.kind, dict(row.payload or {}), row.idempotency_key, row.created_at, row.attempts)
            for key in keys
            if (row := by_key.get(key)) is not None
        ]

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

    async def renew(self, *, job_id: str, owner: str, lease_sec: float) -> bool:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        now = time.time()
        async with get_session() as session:
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.id == job_id,
                    BackgroundJobRow.lease_owner == owner,
                    BackgroundJobRow.leased_until > now,
                )
                .values(leased_until=now + max(1.0, float(lease_sec)))
            )
            await session.commit()
        return bool(result.rowcount)

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

    async def stats(self) -> dict[str, float | int | None]:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        now = time.time()
        active_lease = BackgroundJobRow.status == "leased"
        pending = BackgroundJobRow.status == "pending"
        async with get_session() as session:
            row = (
                await session.execute(
                    select(
                        func.count().filter(pending, BackgroundJobRow.finished_at.is_(None)).label("pending"),
                        func.count().filter(active_lease, BackgroundJobRow.finished_at.is_(None)).label("leased"),
                        func
                        .min(BackgroundJobRow.created_at)
                        .filter(pending, BackgroundJobRow.finished_at.is_(None))
                        .label("oldest_pending"),
                        func.max(BackgroundJobRow.attempts).label("max_attempts"),
                    )
                )
            ).one()
        oldest = float(row.oldest_pending) if row.oldest_pending is not None else None
        return {
            "pending": int(row.pending or 0),
            "leased": int(row.leased or 0),
            "oldest_pending_age_sec": round(max(0.0, now - oldest), 3) if oldest is not None else None,
            "max_attempts": int(row.max_attempts or 0),
        }
