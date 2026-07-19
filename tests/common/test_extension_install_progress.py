from __future__ import annotations

import pytest

from pallas.console.webui.extension_install_progress import (
    create_extension_install_job,
    get_extension_install_job,
    run_extension_install_job,
)


@pytest.mark.asyncio
async def test_extension_install_job_lifecycle() -> None:
    job = await create_extension_install_job("demo-pkg", "install")

    async def runner(package: str) -> dict[str, object]:
        assert package == "demo-pkg"
        return {"message": "ok", "ok": True}

    await run_extension_install_job(job, runner)
    stored = get_extension_install_job(job.job_id)
    assert stored is not None
    assert stored.phase == "done"
    assert stored.result is not None
    assert stored.result.get("message") == "ok"
