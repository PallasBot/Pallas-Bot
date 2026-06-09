from nonebot import get_driver, logger
from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.community_stats.scheduler import start_community_stats_reporter
from src.features.control_plane.bootstrap_client import ensure_control_plane_bootstrap
from src.features.corpus.enroll import ensure_corpus_community_enrolled
from src.platform.bot_runtime.roles import is_sharded_worker

__plugin_meta__ = PluginMetadata(
    name="社区统计上报",
    description="opt-in 向社区统计中心上报部署心跳（默认开启，帮助总览隐藏）。",
    usage="（内部）默认向 stats.pallasbot.top 周期上报；设置 [community_stats] enabled=false 可关闭。",
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
async def community_stats_startup() -> None:
    if is_sharded_worker():
        return
    try:
        await ensure_control_plane_bootstrap()
    except Exception as e:
        logger.warning("control_plane bootstrap: startup failed: {}", e)
    try:
        await ensure_corpus_community_enrolled()
    except Exception as e:
        logger.warning(f"corpus enroll: startup failed: {e}")
    try:
        await start_community_stats_reporter()
    except Exception as e:
        logger.warning(f"community_stats: startup failed: {e}")
