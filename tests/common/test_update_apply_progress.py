"""更新进度 job 单元测试。"""

from __future__ import annotations

import pytest

from packages.pb_webui.manager import map_webui_download_progress
from pallas.console.webui.update_apply_progress import (
    clear_update_apply_jobs_for_tests,
    create_update_apply_job,
    get_update_apply_job,
    has_active_update_apply_job,
    run_update_apply_job,
)


@pytest.fixture(autouse=True)
def _clear_jobs():
    clear_update_apply_jobs_for_tests()
    yield
    clear_update_apply_jobs_for_tests()


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
async def test_has_active_update_apply_job_kinds_and_exclude():
    auto_job = await create_update_apply_job("auto")
    auto_job.push("running", "auto", progress_percent=10)
    assert has_active_update_apply_job() is True
    assert has_active_update_apply_job(kinds=("webui", "bot")) is False
    assert has_active_update_apply_job(exclude_job_id=auto_job.job_id) is False
    web = await create_update_apply_job("webui")
    web.push("running", "web", progress_percent=10)
    assert has_active_update_apply_job(kinds=("webui", "bot")) is True
    assert has_active_update_apply_job(exclude_job_id=web.job_id, kinds=("webui", "bot")) is False


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
