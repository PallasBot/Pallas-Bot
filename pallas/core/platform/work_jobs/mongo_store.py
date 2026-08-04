"""MongoDB 持久化后台任务队列。"""

from __future__ import annotations

import time

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
                "$set": {"status": "leased", "lease_owner": str(owner), "leased_until": now + max(1.0, lease_sec)},
                "$inc": {"attempts": 1},
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        return work_job_from_mongo(BackgroundJob.model_validate(raw)) if raw else None

    async def complete(self, *, job_id: str, owner: str) -> bool:
        return await self._release(job_id=job_id, owner=owner, completed=True, retry_after_sec=0)

    async def fail(self, *, job_id: str, owner: str, retry_after_sec: float) -> bool:
        return await self._release(job_id=job_id, owner=owner, completed=False, retry_after_sec=retry_after_sec)

    async def _release(self, *, job_id: str, owner: str, completed: bool, retry_after_sec: float) -> bool:
        from pallas.core.foundation.db.modules import BackgroundJob

        now = time.time()
        result = await BackgroundJob.get_pymongo_collection().update_one(
            {"job_id": job_id, "lease_owner": owner},
            {
                "$set": {
                    "status": "done" if completed else "pending",
                    "lease_owner": None,
                    "leased_until": None,
                    "finished_at": now if completed else None,
                    "available_at": now + max(0.0, retry_after_sec),
                }
            },
        )
        return bool(result.modified_count)
