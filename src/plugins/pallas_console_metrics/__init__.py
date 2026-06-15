"""分片 worker：注册 matcher/消息控制台指标并刷入共享 stats。"""

from __future__ import annotations

from nonebot import get_driver
from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.platform.shard import context as shard_ctx

__plugin_meta__ = PluginMetadata(
    name="控制台运行指标",
    description="分片 Worker 采集 Matcher 与消息处理指标，写入共享统计文件，由 Hub 侧 WebUI 合并展示运行概况。",
    usage="（内部）无用户命令；分片模式下 Worker 启动时自动挂载指标钩子。",
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "help_audience": "maintainer",
    },
)

driver = get_driver()


@driver.on_startup
async def _boot_worker_console_metrics() -> None:
    if not shard_ctx.sharding_active():
        return
    if not shard_ctx.is_worker():
        return
    from src.plugins.pallas_webui.extended_api import (
        ensure_console_metrics_hooks,
        start_worker_shard_console_stats_sync,
    )

    ensure_console_metrics_hooks()
    start_worker_shard_console_stats_sync()
