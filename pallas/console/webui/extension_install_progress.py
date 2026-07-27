"""官方扩展安装进度（兼容层 → plugin_store_job_progress）。"""

from __future__ import annotations

from pallas.console.webui.plugin_store_job_progress import (
    PluginStoreJob,
    create_plugin_store_job,
    get_plugin_store_job,
    iter_plugin_store_job_sse,
    run_plugin_store_job,
)

ExtensionInstallJob = PluginStoreJob


async def create_extension_install_job(
    package: str,
    action: str,
) -> PluginStoreJob:
    from typing import cast

    from pallas.console.webui.plugin_store_job_progress import StoreAction

    return await create_plugin_store_job(
        kind="official",
        target=package,
        action=cast("StoreAction", action),
    )


def get_extension_install_job(job_id: str) -> PluginStoreJob | None:
    return get_plugin_store_job(job_id)


async def run_extension_install_job(
    job: PluginStoreJob,
    runner,
) -> None:
    async def _runner(j: PluginStoreJob) -> None:
        j.push("running", f"开始{j.action} {j.target}…", progress_percent=5)
        result = await runner(j.target)
        j.result = dict(result)
        j.message = str(result.get("message") or "完成")

    await run_plugin_store_job(job, _runner)


async def iter_extension_install_job_sse(job_id: str):
    async for chunk in iter_plugin_store_job_sse(job_id):
        yield chunk


__all__ = [
    "ExtensionInstallJob",
    "create_extension_install_job",
    "get_extension_install_job",
    "iter_extension_install_job_sse",
    "run_extension_install_job",
]
