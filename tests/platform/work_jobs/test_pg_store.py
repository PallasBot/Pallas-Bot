from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest


def test_postgres_store_is_the_persistent_work_job_store() -> None:
    from pallas.core.platform.work_jobs.pg_store import PostgresWorkJobStore

    assert PostgresWorkJobStore.__name__ == "PostgresWorkJobStore"


def test_requeue_terminal_uses_atomic_conflict_upsert() -> None:
    from sqlalchemy.dialects import postgresql

    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.pg_store import build_requeue_terminal_statement

    job = WorkJob.create(kind="sticker.label.visual", payload={}, idempotency_key="label:hash:1")
    sql = str(build_requeue_terminal_statement(job, now=1.0).compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (idempotency_key) DO UPDATE" in sql
    assert "background_job.status IN" in sql


def test_claim_statement_uses_created_at_without_case_sorting() -> None:
    from sqlalchemy.dialects import postgresql

    from pallas.core.foundation.db.repository_pg import BackgroundJobRow
    from pallas.core.platform.work_jobs.pg_store import build_claim_statement

    statement = build_claim_statement(
        BackgroundJobRow,
        now=1.0,
        limit=8,
        kinds=frozenset({"repeater.message"}),
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "background_job.kind IN" in sql
    assert "ORDER BY background_job.created_at" in sql
    assert "CASE" not in sql


def test_normalize_priority_tiers_removes_filtered_and_duplicate_kinds() -> None:
    from pallas.core.platform.work_jobs.store import normalize_priority_tiers

    assert normalize_priority_tiers(
        (frozenset({"interactive", "repeater.message"}), frozenset({"repeater.message", "repeater.learn"})),
        kinds=frozenset({"interactive", "repeater.message", "repeater.learn"}),
        exclude_kinds=frozenset({"repeater.learn"}),
    ) == (frozenset({"interactive", "repeater.message"}),)


def test_complete_retained_statement_updates_status_done() -> None:
    from sqlalchemy.dialects import postgresql

    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.pg_store import build_complete_retained_statement

    job = WorkJob.create(kind="sticker_vision.select", payload={}, idempotency_key="pg:retain:1")
    stmt = build_complete_retained_statement(job_ids=[job.id], kind="sticker_vision.select", status="done", now=1.0)
    sql = str(stmt.compile(dialect=postgresql.dialect()))

    assert "UPDATE background_job" in sql
    assert "status" in sql
    assert "finished_at" in sql
    assert "lease_owner" in sql and "lease_id" in sql and "leased_until" in sql
    assert "DELETE" not in sql


def test_complete_retained_statement_with_owner_guards_lease_owner() -> None:
    from sqlalchemy.dialects import postgresql

    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.pg_store import build_complete_retained_statement

    job = WorkJob.create(kind="sticker_vision.select", payload={}, idempotency_key="pg:retain:2")
    stmt = build_complete_retained_statement(
        job_ids=[job.id], kind="sticker_vision.select", status="done", now=1.0, owner="w"
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))

    assert "lease_owner" in sql
    assert "lease_owner_1" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["enqueue", "enqueue_many", "requeue_terminal"])
async def test_postgres_job_writes_normalize_nested_nuls_without_mutating_input(monkeypatch, path: str) -> None:
    from sqlalchemy.dialects import postgresql

    from pallas.core.foundation.db import repository_pg
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.pg_store import PostgresWorkJobStore

    payload = {
        "nested": ["left\x00right", {"key\x00": "value\x00"}],
        "tuple": ("tuple\x00", 7, True, None),
        "literal": r"\u0000",
    }
    job = WorkJob.create(kind="image_cache.capture", payload=payload, idempotency_key=f"image:{path}")
    original_payload = copy.deepcopy(job.payload)
    row = SimpleNamespace(
        id=job.id,
        kind=job.kind,
        payload=job.payload,
        idempotency_key=job.idempotency_key,
        created_at=job.created_at,
        attempts=job.attempts,
        lease_id=None,
    )

    class Result:
        def scalar_one(self):
            return row

        def scalar_one_or_none(self):
            return row

        def scalars(self):
            return [row]

        def all(self):
            return [row]

    class Session:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

        async def commit(self):
            pass

    session = Session()

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            pass

    monkeypatch.setattr(repository_pg, "get_session", lambda: SessionContext())
    store = PostgresWorkJobStore()
    if path == "enqueue":
        await store.enqueue(job)
    elif path == "enqueue_many":
        await store.enqueue_many([job])
    else:
        await store.requeue_terminal(job)

    normalized = {
        "nested": ["leftright", {"key": "value"}],
        "tuple": ("tuple", 7, True, None),
        "literal": r"\u0000",
    }
    statement = session.statements[0]
    params = statement.compile(dialect=postgresql.dialect()).params
    assert normalized in params.values()
    assert job.payload == original_payload


@pytest.mark.parametrize(
    "payload",
    [
        {"nested": {"key\x00": 1, "key": 2}},
        {"nested": {1: "integer key", "1": "string key"}},
    ],
)
def test_postgres_job_payload_rejects_unsafe_object_keys(payload: dict[str, object]) -> None:
    from pallas.core.platform.work_jobs.models import InvalidWorkJobPayloadError
    from pallas.core.platform.work_jobs.pg_store import normalize_work_job_payload

    with pytest.raises(InvalidWorkJobPayloadError):
        normalize_work_job_payload(payload)


def test_postgres_job_payload_rejects_non_json_and_circular_values() -> None:
    from pallas.core.platform.work_jobs.models import InvalidWorkJobPayloadError
    from pallas.core.platform.work_jobs.pg_store import normalize_work_job_payload

    circular = []
    circular.append(circular)
    for payload in ({"value": {1, 2}}, {"value": float("nan")}, {"value": circular}):
        with pytest.raises(InvalidWorkJobPayloadError):
            normalize_work_job_payload(payload)
