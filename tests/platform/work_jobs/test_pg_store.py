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
