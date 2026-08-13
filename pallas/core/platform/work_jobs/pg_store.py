"""PostgreSQL 持久化后台任务队列。"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .models import WorkJob


def build_requeue_terminal_statement(job: WorkJob, *, now: float):
    from pallas.core.foundation.db.repository_pg import BackgroundJobRow

    stmt = pg_insert(BackgroundJobRow).values(
        id=job.id,
        kind=job.kind,
        payload=job.payload,
        idempotency_key=job.idempotency_key,
        status="pending",
        attempts=job.attempts,
        available_at=now,
        created_at=job.created_at,
    )
    return stmt.on_conflict_do_update(
        index_elements=["idempotency_key"],
        set_={
            "id": stmt.excluded.id,
            "kind": stmt.excluded.kind,
            "payload": stmt.excluded.payload,
            "status": "pending",
            "attempts": stmt.excluded.attempts,
            "available_at": now,
            "created_at": stmt.excluded.created_at,
            "finished_at": None,
            "last_error": None,
            "lease_owner": None,
            "lease_id": None,
            "leased_until": None,
        },
        where=BackgroundJobRow.status.in_(("done", "dead_letter")),
    ).returning(BackgroundJobRow)


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
        return WorkJob(
            row.id, row.kind, dict(row.payload or {}), row.idempotency_key, row.created_at, row.attempts, row.lease_id
        )

    async def requeue_terminal(self, job: WorkJob) -> tuple[WorkJob, bool]:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session() as session:
            row = (await session.execute(build_requeue_terminal_statement(job, now=time.time()))).scalar_one_or_none()
            reactivated = row is not None
            if row is None:
                row = (
                    await session.execute(
                        select(BackgroundJobRow)
                        .where(BackgroundJobRow.idempotency_key == job.idempotency_key)
                        .with_for_update()
                    )
                ).scalar_one()
            await session.commit()
        return (
            WorkJob(
                row.id,
                row.kind,
                dict(row.payload or {}),
                row.idempotency_key,
                row.created_at,
                row.attempts,
                row.lease_id,
            ),
            reactivated,
        )

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
            WorkJob(
                row.id,
                row.kind,
                dict(row.payload or {}),
                row.idempotency_key,
                row.created_at,
                row.attempts,
                row.lease_id,
            )
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
            row.lease_id = uuid.uuid4().hex
            row.leased_until = now + max(1.0, float(lease_sec))
            row.attempts += 1
            await session.commit()
        return WorkJob(
            row.id, row.kind, dict(row.payload or {}), row.idempotency_key, row.created_at, row.attempts, row.lease_id
        )

    async def claim_many(
        self,
        *,
        owner: str,
        lease_sec: float,
        limit: int,
        kinds: frozenset[str] | None = None,
        exclude_kinds: frozenset[str] | None = None,
        bot_owner_ids: frozenset[int] | None = None,
    ) -> list[WorkJob]:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        now = time.time()
        stmt = select(BackgroundJobRow).where(
            BackgroundJobRow.finished_at.is_(None),
            BackgroundJobRow.available_at <= now,
            or_(BackgroundJobRow.status == "pending", BackgroundJobRow.leased_until < now),
        )
        if kinds is not None:
            stmt = stmt.where(BackgroundJobRow.kind.in_(tuple(kinds)))
        if exclude_kinds is not None:
            stmt = stmt.where(BackgroundJobRow.kind.not_in(tuple(exclude_kinds)))
        if bot_owner_ids is not None:
            stmt = stmt.where(BackgroundJobRow.payload["bot_qq"].astext.in_([str(int(q)) for q in bot_owner_ids]))
        stmt = stmt.order_by(BackgroundJobRow.created_at).with_for_update(skip_locked=True).limit(max(1, int(limit)))
        async with get_session() as session:
            rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                row.status = "leased"
                row.lease_owner = str(owner)
                row.lease_id = uuid.uuid4().hex
                row.leased_until = now + max(1.0, float(lease_sec))
                row.attempts += 1
            await session.commit()
        return [
            WorkJob(
                row.id,
                row.kind,
                dict(row.payload or {}),
                row.idempotency_key,
                row.created_at,
                row.attempts,
                row.lease_id,
            )
            for row in rows
        ]

    async def renew(self, *, job_id: str, owner: str, lease_id: str, lease_sec: float) -> bool:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        now = time.time()
        async with get_session() as session:
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.id == job_id,
                    BackgroundJobRow.lease_owner == owner,
                    BackgroundJobRow.lease_id == lease_id,
                    BackgroundJobRow.leased_until > now,
                )
                .values(leased_until=now + max(1.0, float(lease_sec)))
            )
            await session.commit()
        return bool(result.rowcount)

    async def complete(self, *, job_id: str, owner: str, lease_id: str) -> bool:
        return await self._release(job_id=job_id, owner=owner, lease_id=lease_id, completed=True, retry_after_sec=0)

    async def complete_many(self, *, jobs: list[WorkJob], owner: str) -> int:
        if not jobs:
            return 0
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        now = time.time()
        async with get_session() as session:
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.lease_owner == owner,
                    tuple_(BackgroundJobRow.id, BackgroundJobRow.lease_id).in_([
                        (job.id, job.lease_id) for job in jobs
                    ]),
                )
                .values(
                    status="done", lease_owner=None, lease_id=None, leased_until=None, finished_at=now, available_at=now
                )
            )
            await session.commit()
        return int(result.rowcount or 0)

    async def fail(self, *, job_id: str, owner: str, lease_id: str, retry_after_sec: float) -> bool:
        return await self._release(
            job_id=job_id, owner=owner, lease_id=lease_id, completed=False, retry_after_sec=retry_after_sec
        )

    async def dead_letter(self, *, job_id: str, owner: str, lease_id: str, reason: str) -> bool:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session() as session:
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.id == job_id,
                    BackgroundJobRow.lease_owner == owner,
                    BackgroundJobRow.lease_id == lease_id,
                )
                .values(
                    status="dead_letter", lease_owner=None, lease_id=None, leased_until=None, last_error=reason[:2000]
                )
            )
            await session.commit()
        return bool(result.rowcount)

    async def _release(
        self, *, job_id: str, owner: str, lease_id: str, completed: bool, retry_after_sec: float
    ) -> bool:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        now = time.time()
        values = {
            "status": "done" if completed else "pending",
            "lease_owner": None,
            "lease_id": None,
            "leased_until": None,
            "finished_at": now if completed else None,
            "available_at": now + max(0.0, retry_after_sec),
        }
        async with get_session() as session:
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.id == job_id,
                    BackgroundJobRow.lease_owner == owner,
                    BackgroundJobRow.lease_id == lease_id,
                )
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
                        func.count().filter(BackgroundJobRow.status == "dead_letter").label("dead_lettered"),
                    )
                )
            ).one()
        oldest = float(row.oldest_pending) if row.oldest_pending is not None else None
        return {
            "pending": int(row.pending or 0),
            "leased": int(row.leased or 0),
            "oldest_pending_age_sec": round(max(0.0, now - oldest), 3) if oldest is not None else None,
            "max_attempts": int(row.max_attempts or 0),
            "dead_lettered": int(row.dead_lettered or 0),
        }
