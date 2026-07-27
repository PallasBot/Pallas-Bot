"""插件商店 job 进度单元测试。"""

from __future__ import annotations

import pytest

from pallas.console.webui.plugin_store_job_progress import (
    create_plugin_store_job,
    get_plugin_store_job,
    map_http_download_to_store_progress,
    run_plugin_store_job,
)


@pytest.mark.asyncio
async def test_plugin_store_job_progress_and_complete() -> None:
    job = await create_plugin_store_job(kind="official", target="demo-pkg", action="update")
    assert get_plugin_store_job(job.job_id) is job
    assert job.phase == "queued"
    assert job.package == "demo-pkg"

    async def runner(j) -> None:
        j.push("running", "拉取中", progress_percent=40)
        j.result = {"message": "ok"}
        j.message = "ok"

    await run_plugin_store_job(job, runner)
    assert job.phase == "done"
    assert job.progress_percent == 100
    assert job.result == {"message": "ok"}


@pytest.mark.asyncio
async def test_plugin_store_job_failed_keeps_percent() -> None:
    job = await create_plugin_store_job(kind="community", target="demo", action="uninstall")

    async def runner(j) -> None:
        j.push("failed", error="boom", progress_percent=33)

    await run_plugin_store_job(job, runner)
    assert job.phase == "failed"
    assert job.error == "boom"
    assert job.progress_percent == 33


def test_map_http_download_to_store_progress() -> None:
    seen: list[tuple[int, str]] = []

    def report(pct: int, msg: str) -> None:
        seen.append((pct, msg))

    cb = map_http_download_to_store_progress(report, base=10, span=50)
    assert cb is not None
    cb({"event": "percent", "milestone_percent": 20, "received": 200, "total": 1000})
    cb({"event": "complete", "received": 1000, "total": 1000})
    assert seen[0][0] == 20
    assert "20%" in seen[0][1]
    assert seen[-1][0] == 60
