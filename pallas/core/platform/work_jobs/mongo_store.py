"""MongoDB 持久化后台任务队列。"""

from __future__ import annotations

import time
import uuid

from pymongo import ReturnDocument

from .models import WorkJob


def work_job_from_mongo(row) -> WorkJob:
    return WorkJob(
        id=str(row.job_id),
        kind=str(row.kind),
        payload=dict(row.payload or {}),
        idempotency_key=str(row.idempotency_key),
        created_at=float(row.created_at),
        attempts=int(row.attempts),
        lease_id=getattr(row, "lease_id", None),
    )


class MongoWorkJobStore:
    async def enqueue(self, job: WorkJob) -> WorkJob:
        from pallas.core.foundation.db.modules import BackgroundJob

        row = await BackgroundJob.find_one(BackgroundJob.idempotency_key == job.idempotency_key)
        if row is None:
            try:
                row = BackgroundJob(
                    job_id=job.id,
                    kind=job.kind,
                    payload=job.payload,
                    idempotency_key=job.idempotency_key,
                    attempts=job.attempts,
                    available_at=job.created_at,
                    created_at=job.created_at,
                )
                await row.insert()
            except Exception:
                row = await BackgroundJob.find_one(BackgroundJob.idempotency_key == job.idempotency_key)
                if row is None:
                    raise
        return work_job_from_mongo(row)

    async def enqueue_many(self, jobs: list[WorkJob]) -> list[WorkJob]:
        return [await self.enqueue(job) for job in jobs]

    async def claim(self, *, owner: str, lease_sec: float) -> WorkJob | None:
        from pallas.core.foundation.db.modules import BackgroundJob

        now = time.time()
        collection = BackgroundJob.get_pymongo_collection()
        raw = await collection.find_one_and_update(
            {
                "finished_at": None,
                "available_at": {"$lte": now},
                "$or": [{"status": "pending"}, {"leased_until": {"$lt": now}}],
            },
            {
                "$set": {
                    "status": "leased",
                    "lease_owner": str(owner),
                    "lease_id": uuid.uuid4().hex,
                    "leased_until": now + max(1.0, lease_sec),
                },
                "$inc": {"attempts": 1},
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        return work_job_from_mongo(BackgroundJob.model_validate(raw)) if raw else None

    async def claim_many(self, *, owner: str, lease_sec: float, limit: int) -> list[WorkJob]:
        jobs: list[WorkJob] = []
        for _ in range(max(1, int(limit))):
            job = await self.claim(owner=owner, lease_sec=lease_sec)
            if job is None:
                break
            jobs.append(job)
        return jobs

    async def renew(self, *, job_id: str, owner: str, lease_id: str, lease_sec: float) -> bool:
        from pallas.core.foundation.db.modules import BackgroundJob

        now = time.time()
        result = await BackgroundJob.get_pymongo_collection().update_one(
            {"job_id": job_id, "lease_owner": owner, "lease_id": lease_id, "leased_until": {"$gt": now}},
            {"$set": {"leased_until": now + max(1.0, float(lease_sec))}},
        )
        return bool(result.modified_count)

    async def complete(self, *, job_id: str, owner: str, lease_id: str) -> bool:
        return await self._release(job_id=job_id, owner=owner, lease_id=lease_id, completed=True, retry_after_sec=0)

    async def complete_many(self, *, jobs: list[WorkJob], owner: str) -> int:
        if not jobs:
            return 0
        from pallas.core.foundation.db.modules import BackgroundJob

        now = time.time()
        result = await BackgroundJob.get_pymongo_collection().update_many(
            {"$or": [{"job_id": job.id, "lease_owner": owner, "lease_id": job.lease_id} for job in jobs]},
            {
                "$set": {
                    "status": "done",
                    "lease_owner": None,
                    "lease_id": None,
                    "leased_until": None,
                    "finished_at": now,
                    "available_at": now,
                }
            },
        )
        return int(result.modified_count)

    async def fail(self, *, job_id: str, owner: str, lease_id: str, retry_after_sec: float) -> bool:
        return await self._release(
            job_id=job_id, owner=owner, lease_id=lease_id, completed=False, retry_after_sec=retry_after_sec
        )

    async def _release(
        self, *, job_id: str, owner: str, lease_id: str, completed: bool, retry_after_sec: float
    ) -> bool:
        from pallas.core.foundation.db.modules import BackgroundJob

        now = time.time()
        result = await BackgroundJob.get_pymongo_collection().update_one(
            {"job_id": job_id, "lease_owner": owner, "lease_id": lease_id},
            {
                "$set": {
                    "status": "done" if completed else "pending",
                    "lease_owner": None,
                    "lease_id": None,
                    "leased_until": None,
                    "finished_at": now if completed else None,
                    "available_at": now + max(0.0, retry_after_sec),
                }
            },
        )
        return bool(result.modified_count)

    async def stats(self) -> dict[str, float | int | None]:
        from pallas.core.foundation.db.modules import BackgroundJob

        now = time.time()
        pipeline = [
            {"$match": {"finished_at": None}},
            {
                "$group": {
                    "_id": None,
                    "pending": {"$sum": {"$cond": [{"$eq": ["$status", "pending"]}, 1, 0]}},
                    "leased": {"$sum": {"$cond": [{"$eq": ["$status", "leased"]}, 1, 0]}},
                    "oldest_pending": {"$min": {"$cond": [{"$eq": ["$status", "pending"]}, "$created_at", None]}},
                    "max_attempts": {"$max": "$attempts"},
                }
            },
        ]
        rows = await BackgroundJob.get_pymongo_collection().aggregate(pipeline).to_list(length=1)
        row = rows[0] if rows else {}
        oldest = row.get("oldest_pending")
        return {
            "pending": int(row.get("pending") or 0),
            "leased": int(row.get("leased") or 0),
            "oldest_pending_age_sec": round(max(0.0, now - float(oldest)), 3) if oldest is not None else None,
            "max_attempts": int(row.get("max_attempts") or 0),
        }
