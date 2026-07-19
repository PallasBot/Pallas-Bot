"""控制台数据库备份异步任务。"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from operator import itemgetter
from pathlib import Path
from typing import Any, Literal

from pallas.core.foundation.db.backup import (
    BackupResult,
    backup_info,
    dir_size_bytes,
    prepare_database_backup_run_dir,
    run_database_backup,
    run_database_restore,
)

BackupJobStatus = Literal["queued", "running", "completed", "failed"]
BackupJobKind = Literal["backup", "restore"]

_MAX_JOB_HISTORY = 24
_lock = threading.Lock()
_jobs: dict[str, BackupJobState] = {}


@dataclass
class BackupJobState:
    job_id: str
    job_kind: BackupJobKind = "backup"
    status: BackupJobStatus = "queued"
    output_dir: str = ""
    restore_path: str = ""
    error: str = ""
    result: BackupResult | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    output_parent: str | None = None
    label: str = ""
    scope: str = "full"
    pg_format: str = "custom"
    pg_tables: list[str] = field(default_factory=list)
    mongo_collections: list[str] = field(default_factory=list)


def active_backup_job() -> BackupJobState | None:
    with _lock:
        for job in _jobs.values():
            if job.status in ("queued", "running"):
                return job
    return None


def get_backup_job(job_id: str) -> BackupJobState | None:
    with _lock:
        return _jobs.get(job_id)


def backup_job_status_payload(job: BackupJobState) -> dict[str, Any]:
    size_bytes = 0
    if job.output_dir:
        path = Path(job.output_dir)
        if path.exists():
            size_bytes = dir_size_bytes(path)
    elapsed_sec: float | None = None
    if job.started_at is not None:
        end = job.finished_at if job.finished_at is not None else time.time()
        elapsed_sec = max(0.0, end - job.started_at)
    payload: dict[str, Any] = {
        "job_id": job.job_id,
        "job_kind": job.job_kind,
        "status": job.status,
        "output_dir": job.output_dir,
        "size_bytes": size_bytes,
        "elapsed_sec": elapsed_sec,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
    if job.status == "completed" and job.result is not None:
        payload["result"] = {
            "ok": job.result.ok,
            "backend": job.result.backend,
            "scope": job.result.scope,
            "output_dir": job.result.output_dir,
            "artifacts": job.result.artifacts,
            "size_bytes": job.result.size_bytes,
            "message": job.result.message,
        }
    if job.status == "failed" and job.error:
        payload["error"] = job.error
    return payload


def prune_backup_jobs() -> None:
    with _lock:
        if len(_jobs) <= _MAX_JOB_HISTORY:
            return
        finished = [
            (jid, job.finished_at or job.created_at)
            for jid, job in _jobs.items()
            if job.status in ("completed", "failed")
        ]
        finished.sort(key=itemgetter(1))
        drop = len(_jobs) - _MAX_JOB_HISTORY
        for jid, _ in finished[:drop]:
            _jobs.pop(jid, None)


def start_backup_job(
    *,
    output_parent: str | None = None,
    label: str = "",
    scope: str = "full",
    pg_format: str = "custom",
    pg_tables: list[str] | None = None,
    mongo_collections: list[str] | None = None,
) -> BackupJobState:
    info = backup_info()
    if not info.get("tool_available"):
        tool = str(info.get("tool_name") or "备份工具")
        raise RuntimeError(f"未找到 {tool}，无法发起备份")

    with _lock:
        for job in _jobs.values():
            if job.status in ("queued", "running"):
                raise RuntimeError("已有备份或复原任务进行中，请稍后再试")

        job_id = secrets.token_urlsafe(12)
        job = BackupJobState(
            job_id=job_id,
            output_parent=output_parent,
            label=label,
            scope=scope,
            pg_format=pg_format,
            pg_tables=list(pg_tables or []),
            mongo_collections=list(mongo_collections or []),
        )
        _jobs[job_id] = job
    return job


def run_backup_job_sync(job_id: str) -> None:
    job = get_backup_job(job_id)
    if job is None:
        return

    with _lock:
        job.status = "running"
        job.started_at = time.time()

    try:
        run_dir = prepare_database_backup_run_dir(
            output_parent=job.output_parent,
            label=job.label,
        )
        with _lock:
            job.output_dir = str(run_dir)

        result = run_database_backup(
            output_parent=job.output_parent,
            label=job.label,
            scope=job.scope,  # type: ignore[arg-type]
            pg_format=job.pg_format,  # type: ignore[arg-type]
            pg_tables=job.pg_tables or None,
            mongo_collections=job.mongo_collections or None,
            run_dir=run_dir,
        )
        with _lock:
            job.result = result
            job.status = "completed"
            job.finished_at = time.time()
    except Exception as e:  # noqa: BLE001
        with _lock:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = time.time()
    finally:
        prune_backup_jobs()


def start_restore_job(
    *,
    path: str,
    output_parent: str | None = None,
) -> BackupJobState:
    info = backup_info()
    if not info.get("restore_tool_available"):
        tool = str(info.get("restore_tool_name") or "复原工具")
        raise RuntimeError(f"未找到 {tool}，无法发起复原")

    with _lock:
        for job in _jobs.values():
            if job.status in ("queued", "running"):
                raise RuntimeError("已有备份/复原任务进行中，请稍后再试")

        job_id = secrets.token_urlsafe(12)
        job = BackupJobState(
            job_id=job_id,
            job_kind="restore",
            output_parent=output_parent,
            restore_path=str(path).strip(),
            output_dir=str(path).strip(),
        )
        _jobs[job_id] = job
    return job


def run_restore_job_sync(job_id: str) -> None:
    job = get_backup_job(job_id)
    if job is None or job.job_kind != "restore":
        return

    with _lock:
        job.status = "running"
        job.started_at = time.time()

    try:
        result = run_database_restore(
            job.restore_path,
            output_parent=job.output_parent,
        )
        with _lock:
            job.result = result
            job.status = "completed"
            job.finished_at = time.time()
    except Exception as e:  # noqa: BLE001
        with _lock:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = time.time()
    finally:
        prune_backup_jobs()
