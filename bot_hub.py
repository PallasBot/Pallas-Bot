"""Hub 进程入口：WebUI + 协议端 + relogin（不承载牛牛反向 WS）。

启动前设置::

    PALLAS_SHARD_ENABLED=true
    PALLAS_BOT_ROLE=hub
    PORT=8088
"""

import os

os.environ.setdefault("PALLAS_SHARD_ENABLED", "true")
os.environ.setdefault("PALLAS_BOT_ROLE", "hub")

from pallas.core.foundation.config.dotenv import apply_repo_settings_to_environ

apply_repo_settings_to_environ()


def pin_hub_listen_port() -> None:
    """覆盖 .env 中 PORT，确保 hub 监听注册表 hub_port 而非统一进程 PORT。"""
    from pallas.core.platform.shard.registry.config import get_shard_registry_settings
    from pallas.core.platform.shard.registry.listen_port import apply_listen_port

    apply_listen_port(get_shard_registry_settings().hub_port)


pin_hub_listen_port()

# ruff: noqa: E402
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from pallas.console.web import install_nonebot_log_sink
from pallas.core.foundation.db import init_db
from pallas.core.foundation.logging import apply_stdlib_logging_channel_prefix
from pallas.core.foundation.startup_report import emit_startup_summary
from pallas.core.platform.bot_runtime import load_plugins_for_role
from pallas.core.platform.shard.logs.process import install_shard_process_logging
from pallas.core.platform.shard.registry import get_shard_registry
from pallas.core.platform.shard.registry.config import get_shard_registry_settings
from pallas.core.platform.shard.registry.listen_port import apply_listen_port
from pallas.core.shared.adapters import register_onebot_v11_custom_events
from pallas.core.shared.utils.voice_downloader import ensure_voices
from pallas.product.ban_gate.snapshot import start_ban_gate_snapshot, stop_ban_gate_snapshot
from pallas.product.message_scrub import start_message_scrub_if_enabled

apply_stdlib_logging_channel_prefix()
nonebot.init()
apply_listen_port(get_shard_registry_settings().hub_port)
start_message_scrub_if_enabled()
install_shard_process_logging()
install_nonebot_log_sink()
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
register_onebot_v11_custom_events()


@driver.on_startup
async def startup():
    await init_db()
    from pallas.core.perm.migration import run_acl_startup_migrations

    try:
        await run_acl_startup_migrations()
    except Exception as e:
        nonebot.logger.warning("bot_hub: ACL startup migration failed: {}", e)
    await start_ban_gate_snapshot()
    from pallas.core.platform.coord.redis_settings import ensure_coord_redis_ready_for_sharding

    ensure_coord_redis_ready_for_sharding()
    reg = get_shard_registry()
    nonebot.logger.info(
        "bot_hub: registry hub_port={} worker_base_port={} shards={}",
        reg.hub_port,
        reg.worker_base_port,
        len(reg.shards),
    )
    await ensure_voices()
    try:
        from pallas.core.platform.shard.logs.view import cleanup_stale_shard_log_files

        removed = cleanup_stale_shard_log_files()
        if removed:
            nonebot.logger.info("bot_hub: shard log cleanup: {}", removed)
    except Exception as e:
        nonebot.logger.warning("bot_hub: shard log cleanup failed: {}", e)


@driver.on_shutdown
async def shutdown():
    await stop_ban_gate_snapshot()


load_plugins_for_role()


@driver.on_startup
async def emit_startup_summary_on_startup():
    emit_startup_summary()


if __name__ == "__main__":
    nonebot.run()
