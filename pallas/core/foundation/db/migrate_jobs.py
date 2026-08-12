"""控制台 Mongo→PostgreSQL 迁移异步任务。"""

from __future__ import annotations

import asyncio
import importlib.util
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from nonebot import logger

MigrateJobStatus = Literal["queued", "running", "completed", "failed"]
MigrateJobPhase = Literal[
    "queued",
    "preflight",
    "migrate",
    "verify",
    "switch",
    "rebind",
    "done",
]

_MAX_JOB_HISTORY = 16
_MAX_LOG_LINES = 200
_lock = threading.Lock()
_jobs: dict[str, MigrateJobState] = {}


@dataclass
class MigrateJobState:
    job_id: str
    status: MigrateJobStatus = "queued"
    phase: MigrateJobPhase = "queued"
    dry_run: bool = False
    restart_cursor: bool = False
    switch_backend: bool = True
    try_hot_rebind: bool = True
    batch_size: int = 1000
    tables: list[str] = field(default_factory=list)
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None


def _load_migrate_module():
    mod_name = "pallas_migrate_mongo_to_pg"
    existing = sys.modules.get(mod_name)
    if existing is not None:
        return existing
    root = Path(__file__).resolve().parents[4]
    path = root / "tools" / "migrate_mongo_to_pg.py"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载迁移脚本: {path}")
    mod = importlib.util.module_from_spec(spec)
    # dataclass + from __future__ import annotations 需要模块先挂进 sys.modules
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


def active_migrate_job() -> MigrateJobState | None:
    with _lock:
        for job in _jobs.values():
            if job.status in ("queued", "running"):
                return job
    return None


def get_migrate_job(job_id: str) -> MigrateJobState | None:
    with _lock:
        return _jobs.get(job_id)


def migrate_job_status_payload(job: MigrateJobState) -> dict[str, Any]:
    elapsed_sec: float | None = None
    if job.started_at is not None:
        end = job.finished_at if job.finished_at is not None else time.time()
        elapsed_sec = max(0.0, end - job.started_at)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "phase": job.phase,
        "dry_run": job.dry_run,
        "tables": list(job.tables),
        "logs": list(job.logs[-80:]),
        "result": dict(job.result),
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "elapsed_sec": elapsed_sec,
    }


def prune_migrate_jobs() -> None:
    with _lock:
        if len(_jobs) <= _MAX_JOB_HISTORY:
            return
        finished = sorted(
            (j for j in _jobs.values() if j.status in ("completed", "failed")),
            key=lambda j: j.finished_at or j.created_at,
        )
        while len(_jobs) > _MAX_JOB_HISTORY and finished:
            old = finished.pop(0)
            _jobs.pop(old.job_id, None)


def _append_log(job: MigrateJobState, line: str) -> None:
    job.logs.append(line)
    if len(job.logs) > _MAX_LOG_LINES:
        job.logs = job.logs[-_MAX_LOG_LINES:]


async def _run_migrate_job(job: MigrateJobState) -> None:
    from pallas.core.foundation.db.backend_config import save_db_backend_config
    from pallas.core.foundation.db.runtime_rebind import try_rebind_runtime_backend
    from pallas.core.foundation.db.schema_registry import list_pg_schema_ensure_steps

    job.status = "running"
    job.started_at = time.time()
    job.phase = "preflight"
    logger.info("mongo→pg 迁移开始 job [{}] dry_run [{}] tables [{}]", job.job_id, job.dry_run, len(job.tables or []))
    try:
        mod = _load_migrate_module()
        mod.apply_migrate_env_from_repo()
        tables = set(job.tables) if job.tables else set(mod.ALL_TABLES)
        job.tables = [t for t in mod.ALL_TABLES if t in tables]
        _append_log(job, f"preflight tables={','.join(job.tables)}")
        _append_log(job, f"schema ensure steps={len(list_pg_schema_ensure_steps())}")

        job.phase = "migrate"
        progress: list[str] = []
        migrate_result = await mod.migrate(
            job.batch_size,
            job.dry_run,
            tables,
            None,
            None,
            job.restart_cursor,
            progress=progress,
        )
        for line in progress:
            _append_log(job, line)
        job.result["migrate"] = migrate_result

        if not job.dry_run:
            job.phase = "verify"
            verify = await mod.verify_migration_counts(tables)
            job.result["verify"] = verify
            _append_log(job, f"verify ok={verify.get('ok')}")
            if not verify.get("ok"):
                raise RuntimeError("行数校验未通过，请检查日志后重试或使用 --restart")

            if job.switch_backend:
                job.phase = "switch"
                save_result = save_db_backend_config({"backend": "postgresql"}, force=True)
                job.result["switch"] = save_result
                _append_log(job, save_result.get("message") or "已保存 postgresql 后端")

                if job.try_hot_rebind:
                    job.phase = "rebind"
                    rebind = await try_rebind_runtime_backend("postgresql")
                    job.result["rebind"] = rebind
                    _append_log(job, rebind.get("message") or "rebind done")
                else:
                    job.result["rebind"] = {"ok": False, "restart_required": True, "message": "已跳过热切换"}

        job.phase = "done"
        job.status = "completed"
        job.finished_at = time.time()
        logger.info("mongo→pg 迁移完成 job [{}] switch [{}]", job.job_id, job.switch_backend)
    except Exception as e:  # noqa: BLE001
        logger.exception("mongo→pg migrate job failed")
        job.status = "failed"
        job.error = str(e)
        job.finished_at = time.time()
        _append_log(job, f"ERROR: {e}")
    finally:
        prune_migrate_jobs()


def start_migrate_job(
    *,
    dry_run: bool = False,
    restart_cursor: bool = False,
    switch_backend: bool = True,
    try_hot_rebind: bool = True,
    batch_size: int = 1000,
    tables: list[str] | None = None,
) -> MigrateJobState:
    if active_migrate_job() is not None:
        raise ValueError("已有迁移任务进行中")
    job = MigrateJobState(
        job_id=secrets.token_hex(8),
        dry_run=dry_run,
        restart_cursor=restart_cursor,
        switch_backend=switch_backend and not dry_run,
        try_hot_rebind=try_hot_rebind and not dry_run,
        batch_size=max(100, min(int(batch_size), 5000)),
        tables=list(tables or []),
    )
    with _lock:
        _jobs[job.job_id] = job

    def _runner() -> None:
        asyncio.run(_run_migrate_job(job))

    threading.Thread(target=_runner, name=f"mongo_pg_migrate_{job.job_id}", daemon=True).start()
    return job


def migrate_wizard_info() -> dict[str, Any]:
    from pallas.core.foundation.db.runtime import get_db_backend
    from pallas.core.foundation.db.schema_registry import list_pg_schema_ensure_steps

    mod = _load_migrate_module()
    return {
        "active_backend": get_db_backend(),
        "tables": list(mod.ALL_TABLES),
        "schema_ensure_steps": list_pg_schema_ensure_steps(),
        "notes": [
            "迁移期间建议暂停写入；message 为追加写入，--restart 不会清空业务表。",
            "完整迁移后可自动保存 postgresql 并尝试热切换；失败则需重启 Bot。",
            "LLM 记忆等扩展表暂未纳入本向导，可后续补迁。",
        ],
    }
