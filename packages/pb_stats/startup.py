from nonebot import get_driver, logger

from pallas.core.platform.bot_runtime.roles import is_sharded_worker
from pallas.product.community_stats.scheduler import start_community_stats_reporter
from pallas.product.control_plane.bootstrap_client import ensure_control_plane_bootstrap
from pallas.product.corpus.enroll import ensure_corpus_community_enrolled

driver = get_driver()


@driver.on_startup
async def pb_stats_startup() -> None:
    if is_sharded_worker():
        return
    try:
        await ensure_control_plane_bootstrap()
    except Exception as e:
        logger.warning("control_plane bootstrap: startup failed: {}", e)
    try:
        await ensure_corpus_community_enrolled()
    except Exception as e:
        logger.warning("corpus enroll: startup failed: {}", e)
    try:
        await start_community_stats_reporter()
    except Exception as e:
        logger.warning("pb_stats: startup failed: {}", e)
