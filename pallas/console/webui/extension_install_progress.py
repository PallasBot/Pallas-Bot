"""官方扩展安装进度（内存 job + SSE）。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobPhase = Literal["queued", "running", "done", "failed"]


@dataclass
class ExtensionInstallJob:
    job_id: str
    package: str
    action: Literal["install", "update", "uninstall"]
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


_jobs: dict[str, ExtensionInstallJob] = {}
_jobs_lock = asyncio.Lock()


async def create_extension_install_job(
    package: str,
    action: Literal["install", "update", "uninstall"],
) -> ExtensionInstallJob:
    job = ExtensionInstallJob(job_id=uuid.uuid4().hex, package=package, action=action)
    async with _jobs_lock:
        _jobs[job.job_id] = job
        if len(_jobs) > 32:
            oldest = sorted(_jobs.values(), key=lambda j: j.created_at)[: len(_jobs) - 32]
            for old in oldest:
                _jobs.pop(old.job_id, None)
    return job


def get_extension_install_job(job_id: str) -> ExtensionInstallJob | None:
    return _jobs.get((job_id or "").strip())


async def run_extension_install_job(
    job: ExtensionInstallJob,
    runner,
) -> None:
    job.push("running", f"开始{job.action} {job.package}…")
    try:
        result = await runner(job.package)
        job.push("done", str(result.get("message") or "完成"), result=dict(result))
    except Exception as exc:
        job.push("failed", "安装失败", error=str(exc))


async def iter_extension_install_job_sse(job_id: str):
    """SSE：replay 已有 events，轮询至 done/failed。"""
    job = get_extension_install_job(job_id)
    if job is None:
        yield f"data: {json.dumps({'type': 'error', 'error': 'job_not_found'}, ensure_ascii=False)}\n\n"
        return
    cursor = 0
    yield f"data: {json.dumps({'type': 'ready', 'job_id': job_id, 'package': job.package}, ensure_ascii=False)}\n\n"
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
            break
        yield ": heartbeat\n\n"
        await asyncio.sleep(0.4)
