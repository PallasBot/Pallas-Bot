from __future__ import annotations


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
    stmt = build_complete_retained_statement(job_ids=[job.id], kind="sticker_vision.select", status="done", now=1.0, owner="w")
    sql = str(stmt.compile(dialect=postgresql.dialect()))

    assert "lease_owner" in sql
    assert "lease_owner_1" in sql
