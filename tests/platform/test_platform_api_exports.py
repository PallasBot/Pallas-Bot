from pallas.api import platform as platform_api
from pallas.core.platform.shard.coord.bot_count import STAGGER_SEC as BOT_COUNT_STAGGER_SEC


def test_platform_api_exports_shard_bot_count_stagger_sec() -> None:
    assert platform_api.STAGGER_SEC == BOT_COUNT_STAGGER_SEC
