"""AI Runtime 源码安装进度（内存 job + SSE）。"""

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


@dataclass
class AiInstallJob:
    job_id: str
    action: Literal["clone", "bootstrap", "clone_and_bootstrap"]
    phase: JobPhase = "queued"
    message: str = ""
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)

    def push(
        self,
        phase: JobPhase,
        message: str = "",
        *,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        self.phase = phase
        if message:
            self.message = message
        if result is not None:
            self.result = result
        if error:
            self.error = error
        self.updated_at = time.time()
        self.events.append({
            "phase": phase,
            "message": message or self.message,
            "error": error,
            "ts": self.updated_at,
        })

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "action": self.action,
            "phase": self.phase,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_JOBS: dict[str, AiInstallJob] = {}


def create_ai_install_job(action: Literal["clone", "bootstrap", "clone_and_bootstrap"]) -> AiInstallJob:
    job = AiInstallJob(job_id=str(uuid.uuid4()), action=action)
    job.push("queued", "已排队")
    _JOBS[job.job_id] = job
    return job


def get_ai_install_job(job_id: str) -> AiInstallJob | None:
    return _JOBS.get(job_id)


async def run_ai_install_job(job: AiInstallJob, runner: Callable[[AiInstallJob], None]) -> None:
    try:
        job.push("running", "开始执行")
        await asyncio.to_thread(runner, job)
        if job.phase != "failed":
            job.push("done", job.message or "完成", result=job.result)
    except Exception as e:  # noqa: BLE001
        job.push("failed", error=str(e))


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
            }
            yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
            return
        yield ": heartbeat\n\n"
        await asyncio.sleep(0.4)
