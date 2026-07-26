"""更新进度 job 单元测试。"""

from __future__ import annotations

import pytest

from packages.pb_webui.manager import map_webui_download_progress
from pallas.console.webui.update_apply_progress import (
    create_update_apply_job,
    get_update_apply_job,
    run_update_apply_job,
)


@pytest.mark.asyncio
async def test_update_apply_job_progress_and_complete():
    job = await create_update_apply_job("webui")
    assert get_update_apply_job(job.job_id) is job
    assert job.phase == "queued"

    async def runner(j):
        j.push("running", "下载中", progress_percent=40)
        j.result = {"message": "ok", "tag": "v1"}
        j.message = "ok"

    await run_update_apply_job(job, runner)
    assert job.phase == "done"
    assert job.progress_percent == 100
    assert job.result == {"message": "ok", "tag": "v1"}


@pytest.mark.asyncio
async def test_update_apply_job_failed_stays_failed():
    job = await create_update_apply_job("bot", restart=True)

    async def runner(j):
        j.push("failed", error="boom", progress_percent=33)

    await run_update_apply_job(job, runner)
    assert job.phase == "failed"
    assert job.error == "boom"
    assert job.progress_percent == 33


def test_map_webui_download_progress_percent():
    seen: list[tuple[int, str]] = []

    def report(pct: int, msg: str) -> None:
        seen.append((pct, msg))

    cb = map_webui_download_progress(report, base=10, span=50)
    assert cb is not None
    cb({"event": "percent", "milestone_percent": 20, "received": 200, "total": 1000})
    cb({"event": "complete", "received": 1000, "total": 1000})
    assert seen[0][0] == 20  # 10 + 20*50/100
    assert "20%" in seen[0][1]
    assert seen[-1][0] == 60
