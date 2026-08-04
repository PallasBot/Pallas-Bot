from __future__ import annotations

import pytest


def test_work_job_store_selects_the_configured_database_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.mongo_store import MongoWorkJobStore
    from pallas.core.platform.work_jobs.pg_store import PostgresWorkJobStore
    from pallas.core.platform.work_jobs.runtime import build_work_job_store

    monkeypatch.setattr("pallas.core.foundation.db.get_db_backend", lambda: "postgresql")
    assert isinstance(build_work_job_store(), PostgresWorkJobStore)

    monkeypatch.setattr("pallas.core.foundation.db.get_db_backend", lambda: "mongodb")
    assert isinstance(build_work_job_store(), MongoWorkJobStore)


def test_work_job_store_rejects_an_unknown_database_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.runtime import build_work_job_store

    monkeypatch.setattr("pallas.core.foundation.db.get_db_backend", lambda: "unknown")
    with pytest.raises(RuntimeError, match="unknown"):
        build_work_job_store()
