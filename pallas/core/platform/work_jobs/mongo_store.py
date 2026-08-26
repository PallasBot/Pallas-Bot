"""MongoDB 持久化后台任务队列。"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from pymongo import ReturnDocument

if TYPE_CHECKING:
    from collections.abc import Mapping

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
    def __init__(self, *, completion_retention: Mapping[str, str] | None = None) -> None:
        self._completion_retention: Mapping[str, str] = completion_retention or {}

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

    async def requeue_terminal(self, job: WorkJob) -> tuple[WorkJob, bool]:
        from pallas.core.foundation.db.modules import BackgroundJob

        collection = BackgroundJob.get_pymongo_collection()
        values = {
            "job_id": job.id,
            "kind": job.kind,
            "payload": job.payload,
            "attempts": job.attempts,
            "available_at": job.created_at,
            "created_at": job.created_at,
            "status": "pending",
            "lease_owner": None,
            "lease_id": None,
            "leased_until": None,
            "finished_at": None,
            "last_error": None,
        }
        raw = await collection.find_one_and_update(
            {"idempotency_key": job.idempotency_key, "status": {"$in": ["done", "dead_letter"]}},
            {"$set": values},
            return_document=ReturnDocument.AFTER,
        )
        if raw is not None:
            return work_job_from_mongo(BackgroundJob.model_validate(raw)), True
        try:
            row = BackgroundJob(idempotency_key=job.idempotency_key, **values)
            await row.insert()
        except Exception:
            raw = await collection.find_one({"idempotency_key": job.idempotency_key})
            if raw is None:
                raise
            return work_job_from_mongo(BackgroundJob.model_validate(raw)), False
        return work_job_from_mongo(row), True

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
        from pallas.core.foundation.db.modules import BackgroundJob

        now = time.time()
        collection = BackgroundJob.get_pymongo_collection()
        query: dict = {
            "finished_at": None,
            "available_at": {"$lte": now},
            "$or": [{"status": "pending"}, {"leased_until": {"$lt": now}}],
        }
        if kinds is not None:
            query["kind"] = {"$in": list(kinds)}
        if exclude_kinds is not None:
            query["kind"] = {"$nin": list(exclude_kinds)}
        if bot_owner_ids is not None:
            query["payload.bot_qq"] = {"$in": [int(q) for q in bot_owner_ids]}
        raw = await collection.find_one_and_update(
            query,
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
        jobs: list[WorkJob] = []
        for _ in range(max(1, int(limit))):
            job = await self.claim(
                owner=owner,
                lease_sec=lease_sec,
                kinds=kinds,
                exclude_kinds=exclude_kinds,
                bot_owner_ids=bot_owner_ids,
                priority_kinds=priority_kinds,
            )
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

        collection = BackgroundJob.get_pymongo_collection()
        retained: dict[str, list[WorkJob]] = {}
        removed: list[WorkJob] = []
        for job in jobs:
            if job.kind in self._completion_retention:
                retained.setdefault(job.kind, []).append(job)
            else:
                removed.append(job)
        now = time.time()
        updated = 0
        for kind, kind_jobs in retained.items():
            result = await collection.update_many(
                {
                    "$or": [
                        {"job_id": job.id, "kind": job.kind, "lease_owner": owner, "lease_id": job.lease_id}
                        for job in kind_jobs
                    ]
                },
                {
                    "$set": {
                        "status": self._completion_retention[kind],
                        "finished_at": now,
                        "lease_owner": None,
                        "lease_id": None,
                        "leased_until": None,
                    }
                },
            )
            updated += int(result.modified_count)
        deleted = 0
        if removed:
            result = await collection.delete_many({
                "$or": [{"job_id": job.id, "lease_owner": owner, "lease_id": job.lease_id} for job in removed]
            })
            deleted = int(result.deleted_count)
        return updated + deleted

    async def fail(self, *, job_id: str, owner: str, lease_id: str, retry_after_sec: float) -> bool:
        return await self._release(
            job_id=job_id, owner=owner, lease_id=lease_id, completed=False, retry_after_sec=retry_after_sec
        )

    async def dead_letter(self, *, job_id: str, owner: str, lease_id: str, reason: str) -> bool:
        from pallas.core.foundation.db.modules import BackgroundJob

        result = await BackgroundJob.get_pymongo_collection().update_one(
            {"job_id": job_id, "lease_owner": owner, "lease_id": lease_id},
            {
                "$set": {
                    "status": "dead_letter",
                    "lease_owner": None,
                    "lease_id": None,
                    "leased_until": None,
                    "last_error": reason[:2000],
                }
            },
        )
        return bool(result.modified_count)

    async def _release(
        self, *, job_id: str, owner: str, lease_id: str, completed: bool, retry_after_sec: float
    ) -> bool:
        from pallas.core.foundation.db.modules import BackgroundJob

        collection = BackgroundJob.get_pymongo_collection()
        if completed:
            doc = await collection.find_one({"job_id": job_id, "lease_owner": owner, "lease_id": lease_id})
            if doc is not None and doc.get("kind") in self._completion_retention:
                status = self._completion_retention[doc["kind"]]
                result = await collection.update_one(
                    {"job_id": job_id, "lease_owner": owner, "lease_id": lease_id},
                    {
                        "$set": {
                            "status": status,
                            "finished_at": time.time(),
                            "lease_owner": None,
                            "lease_id": None,
                            "leased_until": None,
                        }
                    },
                )
                return bool(result.modified_count)
            # 已完成任务即时删除，避免集合无限膨胀
            result = await collection.delete_one({"job_id": job_id, "lease_owner": owner, "lease_id": lease_id})
            return bool(result.deleted_count)
        now = time.time()
        result = await collection.update_one(
            {"job_id": job_id, "lease_owner": owner, "lease_id": lease_id},
            {
                "$set": {
                    "status": "pending",
                    "lease_owner": None,
                    "lease_id": None,
                    "leased_until": None,
                    "finished_at": None,
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
                    "dead_lettered": {"$sum": {"$cond": [{"$eq": ["$status", "dead_letter"]}, 1, 0]}},
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
            "dead_lettered": int(row.get("dead_lettered") or 0),
        }
