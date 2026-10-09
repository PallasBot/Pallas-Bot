from __future__ import annotations

from pathlib import Path

import pytest

from pallas.core.foundation.db import backup
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


def test_backup_job_tracks_staging_then_published_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        jobs,
        "backup_info",
        lambda: {"tool_available": True, "tool_name": "pg_dump"},
    )
    staging = tmp_path / ".pallas-backup-postgres_run.staging-test"
    staging.mkdir()
    published = tmp_path / "postgres_run"
    observed: list[str] = []
    job_holder: dict[str, jobs.BackupJobState] = {}

    def prepare(**_kwargs) -> Path:
        return staging

    def run(**kwargs) -> jobs.BackupResult:
        observed.append(kwargs["run_dir"].name)
        (staging / "x.dump").write_bytes(b"dump")
        job = job_holder["job"]
        assert job.status == "running"
        assert job.output_dir == str(staging)
        assert jobs.backup_job_status_payload(job)["size_bytes"] == 4
        return jobs.BackupResult(
            ok=True,
            backend="postgres",
            scope="custom",
            output_dir=str(published),
            artifacts=[str(published / "x.dump")],
            size_bytes=4,
        )

    monkeypatch.setattr(jobs, "prepare_database_backup_run_dir", prepare)
    monkeypatch.setattr(jobs, "run_database_backup", run)
    job = jobs.start_backup_job()
    job_holder["job"] = job
    jobs.run_backup_job_sync(job.job_id)

    assert observed == [staging.name]
    assert job.status == "completed"
    assert job.output_dir == str(published)


@pytest.mark.parametrize("failure", ["probe", "backup", "validation"])
def test_failed_backup_job_removes_owned_staging_dir(tmp_path, monkeypatch, failure) -> None:
    monkeypatch.setattr(
        jobs,
        "backup_info",
        lambda: {"tool_available": True, "tool_name": "pg_dump"},
    )
    monkeypatch.setattr(backup, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(backup, "get_db_backend", lambda: "postgresql")

    if failure == "probe":
        monkeypatch.setattr(backup, "postgres_server_info", lambda: (_ for _ in ()).throw(RuntimeError("probe failed")))
    else:
        monkeypatch.setattr(backup, "postgres_server_info", lambda: (18, "18.3"))
        monkeypatch.setattr(
            backup,
            "select_pg_tool",
            lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18),
        )

        def run_checked(cmd, **_kwargs):
            if cmd[0].endswith("pg_dump"):
                artifact = Path(cmd[cmd.index("-f") + 1])
                artifact.write_bytes(b"archive")
                if failure == "backup":
                    raise RuntimeError("dump failed")
            elif "--file" in cmd:
                raise RuntimeError("archive validation failed")

        monkeypatch.setattr(backup, "_run_checked", run_checked)

    parent = tmp_path / "backups"
    job = jobs.start_backup_job(output_parent=str(parent))
    jobs.run_backup_job_sync(job.job_id)

    assert job.status == "failed"
    assert job.output_dir == ""
    assert list(parent.glob(".*.staging-*")) == []


def test_failed_job_does_not_remove_symlink_target_after_staging_swap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        jobs,
        "backup_info",
        lambda: {"tool_available": True, "tool_name": "pg_dump"},
    )
    monkeypatch.setattr(backup, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(backup, "get_db_backend", lambda: "postgresql")
    parent = tmp_path / "backups"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("valuable")
    staging_holder: list[Path] = []

    def swap_then_fail() -> tuple[int, str]:
        staging = next(parent.glob(".*.staging-*"))
        staging_holder.append(staging)
        staging.rmdir()
        staging.symlink_to(outside, target_is_directory=True)
        raise RuntimeError("probe failed")

    monkeypatch.setattr(backup, "postgres_server_info", swap_then_fail)
    job = jobs.start_backup_job(output_parent=str(parent))
    jobs.run_backup_job_sync(job.job_id)

    assert job.status == "failed"
    assert staging_holder[0].is_symlink()
    assert sentinel.read_text() == "valuable"
