"""分片 worker：注册 matcher/消息控制台指标并刷入共享 stats（hub WebUI 合并读取）。"""

from __future__ import annotations

from nonebot import get_driver

from src.common.shard.registry.config import is_sharding_active

driver = get_driver()


@driver.on_startup
async def _boot_worker_console_metrics() -> None:
    if not is_sharding_active():
        return
    from src.common.bot_runtime.roles import is_sharded_worker

    if not is_sharded_worker():
        return
    from src.plugins.pallas_webui.extended_api import (
        ensure_console_metrics_hooks,
        start_worker_shard_console_stats_sync,
    )

    ensure_console_metrics_hooks()
    start_worker_shard_console_stats_sync()
