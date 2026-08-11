from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}

    async def find_one(self, query: dict[str, object]) -> dict[str, object] | None:
        return next((row.copy() for row in self.rows.values() if _matches(row, query)), None)

    async def find_one_and_update(
        self,
        query: dict[str, object],
        update: dict[str, dict[str, object]],
        **_: object,
    ) -> dict[str, object] | None:
        row = next((row for row in self.rows.values() if _matches(row, query)), None)
        if row is None:
            return None
        row.update(update["$set"])
        return row.copy()


def _matches(row: dict[str, object], query: dict[str, object]) -> bool:
    for key, expected in query.items():
        if isinstance(expected, dict) and "$in" in expected:
            if row.get(key) not in expected["$in"]:
                return False
        elif row.get(key) != expected:
            return False
    return True


class _FakeBackgroundJob:
    collection = _FakeCollection()

    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)

    async def insert(self) -> None:
        if self.idempotency_key in self.collection.rows:
            raise RuntimeError("duplicate idempotency key")
        self.collection.rows[self.idempotency_key] = self.__dict__.copy()

    @classmethod
    def get_pymongo_collection(cls) -> _FakeCollection:
        return cls.collection

    @classmethod
    def model_validate(cls, row: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(**row)


@pytest.fixture
def mongo_store(monkeypatch: pytest.MonkeyPatch):
    from pallas.core.foundation.db import modules
    from pallas.core.platform.work_jobs.mongo_store import MongoWorkJobStore

    _FakeBackgroundJob.collection = _FakeCollection()
    monkeypatch.setattr(modules, "BackgroundJob", _FakeBackgroundJob)
    return MongoWorkJobStore()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "leased"])
async def test_mongo_requeue_terminal_does_not_reactivate_active_same_job(mongo_store, status: str) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob

    job = WorkJob.create(kind="test", payload={"value": 1}, idempotency_key="test:mongo:active")
    _FakeBackgroundJob.collection.rows[job.idempotency_key] = _row_from_job(job, status=status)

    result, reactivated = await mongo_store.requeue_terminal(job)

    assert result.id == job.id
    assert reactivated is False


@pytest.mark.asyncio
async def test_mongo_requeue_terminal_reports_new_insert(mongo_store) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob

    job = WorkJob.create(kind="test", payload={"value": 1}, idempotency_key="test:mongo:new")

    result, reactivated = await mongo_store.requeue_terminal(job)

    assert result == job
    assert reactivated is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["done", "dead_letter"])
async def test_mongo_requeue_terminal_reactivates_terminal_job(mongo_store, status: str) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob

    original = WorkJob.create(kind="test", payload={"value": 1}, idempotency_key="test:mongo:terminal")
    replacement = WorkJob.create(kind="test", payload={"value": 2}, idempotency_key="test:mongo:terminal")
    _FakeBackgroundJob.collection.rows[original.idempotency_key] = _row_from_job(
        original,
        status=status,
        attempts=3,
        finished_at=1.0,
        last_error="failed",
    )

    result, reactivated = await mongo_store.requeue_terminal(replacement)

    assert reactivated is True
    assert result.id == replacement.id
    assert result.payload == {"value": 2}
    assert _FakeBackgroundJob.collection.rows[replacement.idempotency_key] == {
        "job_id": replacement.id,
        "kind": replacement.kind,
        "payload": replacement.payload,
        "idempotency_key": replacement.idempotency_key,
        "attempts": 0,
        "available_at": replacement.created_at,
        "created_at": replacement.created_at,
        "status": "pending",
        "lease_owner": None,
        "lease_id": None,
        "leased_until": None,
        "finished_at": None,
        "last_error": None,
    }


def _row_from_job(job, *, status: str, **overrides: object) -> dict[str, object]:
    return {
        "job_id": job.id,
        "kind": job.kind,
        "payload": job.payload,
        "idempotency_key": job.idempotency_key,
        "status": status,
        "attempts": job.attempts,
        "available_at": job.created_at,
        "leased_until": None,
        "lease_owner": None,
        "lease_id": None,
        "last_error": None,
        "created_at": job.created_at,
        "finished_at": None,
        **overrides,
    }
