from __future__ import annotations

import pytest

from pallas.core.foundation.db import backup_jobs as jobs


@pytest.fixture(autouse=True)
def clear_jobs() -> None:
    with jobs._lock:
        jobs._jobs.clear()
    yield
    with jobs._lock:
        jobs._jobs.clear()


def test_start_backup_job_rejects_parallel(monkeypatch) -> None:
    monkeypatch.setattr(
        jobs,
        "backup_info",
        lambda: {"tool_available": True, "tool_name": "pg_dump"},
    )
    jobs.start_backup_job()
    with pytest.raises(RuntimeError, match="进行中"):
        jobs.start_backup_job()


def test_backup_job_status_payload_size(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        jobs,
        "backup_info",
        lambda: {"tool_available": True, "tool_name": "pg_dump"},
    )
    job = jobs.start_backup_job()
    run_dir = tmp_path / "postgres_test"
    run_dir.mkdir()
    (run_dir / "a.dump").write_bytes(b"x" * 2048)
    with jobs._lock:
        job.status = "running"
        job.output_dir = str(run_dir)
    payload = jobs.backup_job_status_payload(job)
    assert payload["size_bytes"] == 2048
    assert payload["status"] == "running"
