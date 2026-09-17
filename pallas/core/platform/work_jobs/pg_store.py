"""PostgreSQL 持久化后台任务队列。"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, func, or_, select, tuple_, update

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .models import WorkJob
from .store import normalize_priority_tiers


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


def build_complete_retained_statement(
    job_ids: list[str], *, kind: str, status: str, now: float, owner: str | None = None
):
    from pallas.core.foundation.db.repository_pg import BackgroundJobRow

    where_conds = [BackgroundJobRow.id.in_(job_ids), BackgroundJobRow.kind == kind]
    if owner is not None:
        where_conds.append(BackgroundJobRow.lease_owner == owner)
    return (
        update(BackgroundJobRow)
        .where(*where_conds)
        .values(
            status=status,
            finished_at=now,
            lease_owner=None,
            lease_id=None,
            leased_until=None,
        )
    )


def build_claim_statement(
    row_model,
    *,
    now: float,
    limit: int,
    kinds: frozenset[str] | None = None,
    exclude_kinds: frozenset[str] | None = None,
    bot_owner_ids: frozenset[int] | None = None,
):
    conditions = [
        row_model.finished_at.is_(None),
        row_model.available_at <= now,
        or_(row_model.status == "pending", and_(row_model.status == "leased", row_model.leased_until < now)),
    ]
    if kinds is not None:
        conditions.append(row_model.kind.in_(tuple(kinds)))
    if exclude_kinds:
        conditions.append(row_model.kind.not_in(tuple(exclude_kinds)))
    if bot_owner_ids is not None:
        conditions.append(row_model.payload["bot_qq"].astext.in_([str(int(q)) for q in bot_owner_ids]))
    return (
        select(row_model)
        .where(*conditions)
        .order_by(row_model.created_at)
        .with_for_update(skip_locked=True)
        .limit(max(1, int(limit)))
    )


async def load_claim_rows(
    session,
    row_model,
    *,
    now: float,
    limit: int,
    kinds: frozenset[str] | None = None,
    exclude_kinds: frozenset[str] | None = None,
    bot_owner_ids: frozenset[int] | None = None,
):
    if kinds is not None and not kinds:
        return []
    result = await session.execute(
        build_claim_statement(
            row_model,
            now=now,
            limit=limit,
            kinds=kinds,
            exclude_kinds=exclude_kinds,
            bot_owner_ids=bot_owner_ids,
        )
    )
    return list(result.scalars().all())


class PostgresWorkJobStore:
    def __init__(
        self,
        *,
        completion_retention: Mapping[str, str] | None = None,
        notify_completed: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._completion_retention: Mapping[str, str] = completion_retention or {}
        self._notify_completed = notify_completed

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
        from pallas.core.platform.observability import SlowPathTimer, slow_path_threshold_ms

        timer = SlowPathTimer(
            "work_jobs.enqueue_many",
            threshold_ms=slow_path_threshold_ms("PALLAS_SLOW_ENQUEUE_MANY_MS", 300.0),
            log_level="debug",
        )

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
        timer.finish(jobs=len(jobs))
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

    async def claim(
        self,
        *,
        owner: str,
        lease_sec: float,
        kinds: frozenset[str] | None = None,
        exclude_kinds: frozenset[str] | None = None,
        bot_owner_ids: frozenset[int] | None = None,
        priority_tiers: tuple[frozenset[str], ...] | None = None,
    ) -> WorkJob | None:
        jobs = await self.claim_many(
            owner=owner,
            lease_sec=lease_sec,
            limit=1,
            kinds=kinds,
            exclude_kinds=exclude_kinds,
            bot_owner_ids=bot_owner_ids,
            priority_tiers=priority_tiers,
        )
        return jobs[0] if jobs else None

    async def claim_many(
        self,
        *,
        owner: str,
        lease_sec: float,
        limit: int,
        kinds: frozenset[str] | None = None,
        exclude_kinds: frozenset[str] | None = None,
        bot_owner_ids: frozenset[int] | None = None,
        priority_tiers: tuple[frozenset[str], ...] | None = None,
    ) -> list[WorkJob]:
        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session
        from pallas.core.platform.observability import SlowPathTimer, slow_path_threshold_ms

        timer = SlowPathTimer(
            "work_jobs.claim_many",
            threshold_ms=slow_path_threshold_ms("PALLAS_SLOW_CLAIM_MANY_MS", 300.0),
            log_level="debug",
        )
        now = time.time()
        batch_limit = max(1, int(limit))
        async with get_session() as session:
            tiers = normalize_priority_tiers(priority_tiers, kinds=kinds, exclude_kinds=exclude_kinds)
            rows = []
            tier_kinds = frozenset(kind for tier in tiers for kind in tier)
            if tiers:
                # 每个 kind 单独取候选，再在内存合并，避免跨 kind ORDER BY 触发全量排序。
                for tier in tiers:
                    tier_limit = batch_limit - len(rows)
                    candidates = []
                    for kind in sorted(tier):
                        candidates.extend(
                            await load_claim_rows(
                                session,
                                BackgroundJobRow,
                                now=now,
                                limit=tier_limit,
                                kinds=frozenset({kind}),
                                bot_owner_ids=bot_owner_ids,
                            )
                        )
                    rows.extend(sorted(candidates, key=lambda row: (row.created_at, row.id))[:tier_limit])
                    if len(rows) >= batch_limit:
                        break
                if len(rows) < batch_limit:
                    fallback_exclude = frozenset((exclude_kinds or set()) | set(tier_kinds))
                    rows.extend(
                        await load_claim_rows(
                            session,
                            BackgroundJobRow,
                            now=now,
                            limit=batch_limit - len(rows),
                            kinds=kinds,
                            exclude_kinds=fallback_exclude,
                            bot_owner_ids=bot_owner_ids,
                        )
                    )
            else:
                rows = await load_claim_rows(
                    session,
                    BackgroundJobRow,
                    now=now,
                    limit=batch_limit,
                    kinds=kinds,
                    exclude_kinds=exclude_kinds,
                    bot_owner_ids=bot_owner_ids,
                )
            timer.mark("query")
            for row in rows:
                row.status = "leased"
                row.lease_owner = str(owner)
                row.lease_id = uuid.uuid4().hex
                row.leased_until = now + max(1.0, float(lease_sec))
                row.attempts += 1
            await session.commit()
        timer.finish(owner=owner, limit=batch_limit, rows=len(rows))
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

        retained: dict[str, list[WorkJob]] = {}
        removed: list[WorkJob] = []
        for job in jobs:
            if job.kind in self._completion_retention:
                retained.setdefault(job.kind, []).append(job)
            else:
                removed.append(job)

        updated = 0
        deleted = 0
        async with get_session() as session:
            now = time.time()
            for kind, kind_jobs in retained.items():
                result = await session.execute(
                    build_complete_retained_statement(
                        job_ids=[job.id for job in kind_jobs],
                        kind=kind,
                        status=self._completion_retention[kind],
                        now=now,
                        owner=owner,
                    )
                )
                updated += int(result.rowcount or 0)
            if removed:
                result = await session.execute(
                    delete(BackgroundJobRow).where(
                        BackgroundJobRow.lease_owner == owner,
                        tuple_(BackgroundJobRow.id, BackgroundJobRow.lease_id).in_([
                            (job.id, job.lease_id) for job in removed
                        ]),
                    )
                )
                deleted += int(result.rowcount or 0)
            await session.commit()
        if updated > 0 and self._notify_completed is not None:
            await self._notify_completed()
        return updated + deleted

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

        async with get_session() as session:
            if completed:
                row = (
                    await session.execute(
                        select(BackgroundJobRow).where(
                            BackgroundJobRow.id == job_id,
                            BackgroundJobRow.lease_owner == owner,
                            BackgroundJobRow.lease_id == lease_id,
                        )
                    )
                ).scalar_one_or_none()
                if row is not None and row.kind in self._completion_retention:
                    await session.execute(
                        build_complete_retained_statement(
                            job_ids=[job_id],
                            kind=row.kind,
                            status=self._completion_retention[row.kind],
                            now=time.time(),
                        )
                    )
                    await session.commit()
                    if self._notify_completed is not None:
                        await self._notify_completed()
                    return True
                # 已完成任务即时删除，避免表无限膨胀；幂等防重由 enqueue 的 idempotency 唯一约束承担
                result = await session.execute(
                    delete(BackgroundJobRow).where(
                        BackgroundJobRow.id == job_id,
                        BackgroundJobRow.lease_owner == owner,
                        BackgroundJobRow.lease_id == lease_id,
                    )
                )
            else:
                now = time.time()
                result = await session.execute(
                    update(BackgroundJobRow)
                    .where(
                        BackgroundJobRow.id == job_id,
                        BackgroundJobRow.lease_owner == owner,
                        BackgroundJobRow.lease_id == lease_id,
                    )
                    .values(
                        status="pending",
                        lease_owner=None,
                        lease_id=None,
                        leased_until=None,
                        finished_at=None,
                        available_at=now + max(0.0, retry_after_sec),
                    )
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
