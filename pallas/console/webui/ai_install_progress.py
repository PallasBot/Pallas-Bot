"""AI Runtime 源码安装进度（内存 job + SSE）。

百分比策略：clone / bootstrap / writeback 用估算里程碑；
bootstrap 过程按输出行在 ``[bootstrap_base, bootstrap_cap]`` 内缓升。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

JobPhase = Literal["queued", "running", "done", "failed"]
InstallAction = Literal["clone", "bootstrap", "clone_and_bootstrap", "update"]

# clone_and_bootstrap / update 里程碑
PCT_QUEUED = 0
PCT_START = 5
PCT_CLONE = 10
PCT_CLONE_DONE = 40
PCT_UPDATE = 12
PCT_UPDATE_DONE = 40
PCT_BOOTSTRAP = 45
PCT_BOOTSTRAP_CAP = 88
PCT_WRITEBACK = 92
PCT_DONE = 100

_MAX_LOG_LINES = 500


@dataclass
class AiInstallJob:
    job_id: str
    action: InstallAction
    phase: JobPhase = "queued"
    message: str = ""
    progress_percent: int = 0
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)

    def push(
        self,
        phase: JobPhase,
        message: str = "",
        *,
        progress_percent: int | None = None,
        result: dict[str, Any] | None = None,
        error: str = "",
        line: str | None = None,
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
        if line is not None:
            text = str(line).rstrip("\n")
            self.log_lines.append(text)
            if len(self.log_lines) > _MAX_LOG_LINES:
                self.log_lines = self.log_lines[-(_MAX_LOG_LINES - 100) :]
        self.updated_at = time.time()
        event: dict[str, Any] = {
            "phase": phase,
            "message": message or self.message,
            "progress_percent": self.progress_percent,
            "error": error,
            "ts": self.updated_at,
        }
        if line is not None:
            event["line"] = str(line).rstrip("\n")
        self.events.append(event)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "action": self.action,
            "phase": self.phase,
            "message": self.message,
            "progress_percent": self.progress_percent,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "log_lines": list(self.log_lines[-80:]),
        }


_JOBS: dict[str, AiInstallJob] = {}


def create_ai_install_job(action: InstallAction) -> AiInstallJob:
    job = AiInstallJob(job_id=str(uuid.uuid4()), action=action)
    job.push("queued", "已排队", progress_percent=PCT_QUEUED)
    _JOBS[job.job_id] = job
    if len(_JOBS) > 32:
        oldest = sorted(_JOBS.values(), key=lambda j: j.created_at)[: len(_JOBS) - 32]
        for old in oldest:
            _JOBS.pop(old.job_id, None)
    return job


def get_ai_install_job(job_id: str) -> AiInstallJob | None:
    return _JOBS.get(job_id)


def bootstrap_line_progress(line_index: int) -> int:
    """bootstrap 输出行对应的缓升百分比（不含封顶后的 writeback）。"""
    return min(PCT_BOOTSTRAP_CAP, PCT_BOOTSTRAP + max(0, int(line_index)))


async def run_ai_install_job(job: AiInstallJob, runner: Callable[[AiInstallJob], None]) -> None:
    try:
        if job.phase == "queued":
            job.push("running", "开始执行", progress_percent=max(job.progress_percent, PCT_START))
        await asyncio.to_thread(runner, job)
        if job.phase != "failed":
            job.push(
                "done",
                job.message or "完成",
                progress_percent=PCT_DONE,
                result=job.result,
            )
    except Exception as e:  # noqa: BLE001
        if job.phase != "failed":
            job.push("failed", error=str(e), progress_percent=job.progress_percent)


async def iter_ai_install_job_sse(job_id: str) -> AsyncIterator[str]:
    job = get_ai_install_job(job_id)
    if job is None:
        yield f"data: {json.dumps({'type': 'error', 'error': 'job_not_found'}, ensure_ascii=False)}\n\n"
        return
    cursor = 0
    yield f"data: {json.dumps({'type': 'ready', 'job_id': job_id, 'action': job.action}, ensure_ascii=False)}\n\n"
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
                "action": job.action,
                "log_lines": list(job.log_lines[-80:]),
            }
            yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
            return
        yield ": heartbeat\n\n"
        await asyncio.sleep(0.35)
