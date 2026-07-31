"""Bot / WebUI 在线更新进度（内存 job + SSE / 快照）。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

JobPhase = Literal["queued", "running", "done", "failed"]
UpdateKind = Literal["webui", "bot", "auto"]


@dataclass
class UpdateApplyJob:
    job_id: str
    kind: UpdateKind
    phase: JobPhase = "queued"
    message: str = ""
    progress_percent: int = 0
    result: dict[str, Any] | None = None
    error: str = ""
    restart: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)

    def push(
        self,
        phase: JobPhase,
        message: str = "",
        *,
        progress_percent: int | None = None,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        self.phase = phase
        if message:
            self.message = message
        if progress_percent is not None:
            self.progress_percent = max(0, min(100, int(progress_percent)))
        if result is not None:
            self.result = result
        if error:
            self.error = error
        self.updated_at = time.time()
        self.events.append({
            "phase": phase,
            "message": message or self.message,
            "progress_percent": self.progress_percent,
            "error": error,
            "ts": self.updated_at,
        })

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "phase": self.phase,
            "message": self.message,
            "progress_percent": self.progress_percent,
            "result": self.result,
            "error": self.error,
            "restart": self.restart,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_JOBS: dict[str, UpdateApplyJob] = {}
_JOBS_LOCK = asyncio.Lock()


async def create_update_apply_job(kind: UpdateKind, *, restart: bool = False) -> UpdateApplyJob:
    job = UpdateApplyJob(job_id=uuid.uuid4().hex, kind=kind, restart=restart)
    job.push("queued", "已排队", progress_percent=0)
    async with _JOBS_LOCK:
        _JOBS[job.job_id] = job
        if len(_JOBS) > 32:
            oldest = sorted(_JOBS.values(), key=lambda j: j.created_at)[: len(_JOBS) - 32]
            for old in oldest:
                _JOBS.pop(old.job_id, None)
    return job


def clear_update_apply_jobs_for_tests() -> None:
    """仅供单元测试清理进程内 job 表。"""
    _JOBS.clear()


def get_update_apply_job(job_id: str) -> UpdateApplyJob | None:
    return _JOBS.get((job_id or "").strip())


def get_active_update_apply_job(
    *,
    kinds: tuple[UpdateKind, ...] | None = None,
) -> UpdateApplyJob | None:
    running = [
        job
        for job in _JOBS.values()
        if job.phase in ("queued", "running") and (kinds is None or job.kind in kinds)
    ]
    if not running:
        return None
    return max(running, key=lambda j: j.updated_at)


def has_active_update_apply_job(
    *,
    exclude_job_id: str | None = None,
    kinds: tuple[UpdateKind, ...] | None = None,
) -> bool:
    """是否存在排队中或执行中的更新任务。

    exclude_job_id：忽略自身（例如 auto run-once 任务在跑目标时）。
    kinds：仅匹配指定 kind；默认全部。目标 runner 应传 ``("webui", "bot")``，
    避免把本轮的 ``auto`` job 当成 busy。
    """
    exclude = (exclude_job_id or "").strip() or None
    for job in _JOBS.values():
        if exclude and job.job_id == exclude:
            continue
        if kinds is not None and job.kind not in kinds:
            continue
        if job.phase in ("queued", "running"):
            return True
    return False


async def run_update_apply_job(
    job: UpdateApplyJob,
    runner: Callable[[UpdateApplyJob], Awaitable[None]],
) -> None:
    try:
        job.push("running", "开始执行", progress_percent=max(job.progress_percent, 1))
        await runner(job)
        if job.phase != "failed":
            job.push(
                "done",
                job.message or "完成",
                progress_percent=100,
                result=job.result,
            )
    except Exception as e:  # noqa: BLE001
        job.push("failed", error=str(e), progress_percent=job.progress_percent)


async def iter_update_apply_job_sse(job_id: str) -> AsyncIterator[str]:
    job = get_update_apply_job(job_id)
    if job is None:
        yield f"data: {json.dumps({'type': 'error', 'error': 'job_not_found'}, ensure_ascii=False)}\n\n"
        return
    cursor = 0
    yield f"data: {json.dumps({'type': 'ready', 'job_id': job_id, 'kind': job.kind}, ensure_ascii=False)}\n\n"
    while True:
        while cursor < len(job.events):
            payload = {"type": "progress", **job.events[cursor]}
            cursor += 1
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        if job.phase in ("done", "failed"):
            final = {
                "type": "complete",
                "phase": job.phase,
                "message": job.message,
                "error": job.error,
                "result": job.result,
                "progress_percent": job.progress_percent,
                "kind": job.kind,
            }
            yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
            return
        yield ": heartbeat\n\n"
        await asyncio.sleep(0.35)
