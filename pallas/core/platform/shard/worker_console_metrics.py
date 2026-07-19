"""分片 worker 控制台指标。"""

from __future__ import annotations

from nonebot import get_driver

from pallas.core.platform.shard import context as shard_ctx

_registered = False


def register_worker_console_metrics_startup() -> None:
    global _registered
    if _registered:
        return
    if not shard_ctx.sharding_active() or not shard_ctx.is_worker():
        return
    _registered = True
    driver = get_driver()

    @driver.on_startup
    async def boot_worker_console_metrics() -> None:
        from packages.pb_webui.extended_api import (
            ensure_console_metrics_hooks,
            start_worker_shard_console_stats_sync,
        )

        ensure_console_metrics_hooks()
        start_worker_shard_console_stats_sync()
