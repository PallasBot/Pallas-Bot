"""插件商店装/更/卸进度（内存 job + SSE）。

百分比策略：有 HTTP ``Content-Length`` 下载时按字节映射到区间；
git / uv pip 等无字节流的阶段用估算里程碑。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pallas.core.shared.utils.stream_download import StreamDownloadProgress

JobPhase = Literal["queued", "running", "done", "failed"]
StoreKind = Literal["official", "community"]
StoreAction = Literal["install", "update", "uninstall"]
ProgressReporter = Callable[[int, str], None]


@dataclass
class PluginStoreJob:
    job_id: str
    kind: StoreKind
    target: str
    action: StoreAction
    phase: JobPhase = "queued"
    message: str = ""
    progress_percent: int = 0
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def package(self) -> str:
        """兼容旧 install job 字段名。"""
        return self.target

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
            "target": self.target,
            "package": self.target,
            "action": self.action,
            "phase": self.phase,
            "message": self.message,
            "progress_percent": self.progress_percent,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_JOBS: dict[str, PluginStoreJob] = {}
_JOBS_LOCK = asyncio.Lock()


async def create_plugin_store_job(
    *,
    kind: StoreKind,
    target: str,
    action: StoreAction,
) -> PluginStoreJob:
    job = PluginStoreJob(
        job_id=uuid.uuid4().hex,
        kind=kind,
        target=(target or "").strip(),
        action=action,
    )
    job.push("queued", "已排队", progress_percent=0)
    async with _JOBS_LOCK:
        _JOBS[job.job_id] = job
        if len(_JOBS) > 32:
            oldest = sorted(_JOBS.values(), key=lambda j: j.created_at)[: len(_JOBS) - 32]
            for old in oldest:
                _JOBS.pop(old.job_id, None)
    return job


def get_plugin_store_job(job_id: str) -> PluginStoreJob | None:
    return _JOBS.get((job_id or "").strip())


def get_active_plugin_store_job() -> PluginStoreJob | None:
    running = [j for j in _JOBS.values() if j.phase in ("queued", "running")]
    if not running:
        return None
    return max(running, key=lambda j: j.updated_at)


def job_progress_reporter(job: PluginStoreJob) -> ProgressReporter:
    def report(percent: int, message: str = "") -> None:
        job.push("running", message, progress_percent=percent)

    return report


def map_http_download_to_store_progress(
    report: ProgressReporter | None,
    *,
    base: int = 20,
    span: int = 55,
) -> Callable[[StreamDownloadProgress], None] | None:
    """将流式下载事件映射到 ``[base, base+span]``（有总大小时按字节百分比）。"""
    if report is None:
        return None

    from pallas.core.shared.utils.stream_download import format_download_byte_size

    unknown_pct = base + 8

    def _on(ev: StreamDownloadProgress) -> None:
        nonlocal unknown_pct
        if ev["event"] == "percent":
            pct = base + int(ev["milestone_percent"] * span / 100)
            report(
                pct,
                f"下载中 {ev['milestone_percent']}%（{format_download_byte_size(ev['received'])}"
                f" / {format_download_byte_size(ev['total'])}）",
            )
        elif ev["event"] == "unknown_step":
            unknown_pct = min(base + span - 4, unknown_pct + 4)
            report(unknown_pct, f"下载中 {format_download_byte_size(ev['received'])}（未知总大小）")
        elif ev["event"] == "complete":
            report(base + span, f"下载完成 {format_download_byte_size(ev['received'])}")

    return _on


async def run_plugin_store_job(
    job: PluginStoreJob,
    runner: Callable[[PluginStoreJob], Awaitable[None]],
) -> None:
    try:
        if job.phase == "queued":
            job.push("running", "开始执行", progress_percent=max(job.progress_percent, 1))
        await runner(job)
        if job.phase != "failed":
            job.push(
                "done",
                job.message or "完成",
                progress_percent=100,
                result=job.result,
            )
    except Exception as exc:  # noqa: BLE001
        if job.phase != "failed":
            job.push("failed", error=str(exc), progress_percent=job.progress_percent)


async def iter_plugin_store_job_sse(job_id: str) -> AsyncIterator[str]:
    job = get_plugin_store_job(job_id)
    if job is None:
        yield f"data: {json.dumps({'type': 'error', 'error': 'job_not_found'}, ensure_ascii=False)}\n\n"
        return
    cursor = 0
    ready = {
        "type": "ready",
        "job_id": job_id,
        "kind": job.kind,
        "target": job.target,
        "action": job.action,
    }
    yield f"data: {json.dumps(ready, ensure_ascii=False)}\n\n"
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
                "target": job.target,
                "action": job.action,
            }
            yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
            return
        yield ": heartbeat\n\n"
        await asyncio.sleep(0.35)
