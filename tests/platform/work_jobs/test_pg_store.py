from __future__ import annotations


def test_postgres_store_is_the_persistent_work_job_store() -> None:
    from pallas.core.platform.work_jobs.pg_store import PostgresWorkJobStore

    assert PostgresWorkJobStore.__name__ == "PostgresWorkJobStore"
