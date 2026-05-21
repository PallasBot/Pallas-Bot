"""Hub 进程入口：WebUI + 协议端 + relogin（不承载牛牛反向 WS）。

启动前设置::

    PALLAS_SHARD_ENABLED=true
    PALLAS_BOT_ROLE=hub
    PORT=8088
"""

import os

os.environ.setdefault("PALLAS_SHARD_ENABLED", "true")
os.environ.setdefault("PALLAS_BOT_ROLE", "hub")


def pin_hub_listen_port() -> None:
    """覆盖 .env 中 PORT，确保 hub 监听注册表 hub_port 而非统一进程 PORT。"""
    from src.common.shard.registry.config import get_shard_registry_settings
    from src.common.shard.registry.listen_port import apply_listen_port

    apply_listen_port(get_shard_registry_settings().hub_port)


pin_hub_listen_port()

# ruff: noqa: E402
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from src.common.ban_gate.snapshot import start_ban_gate_snapshot, stop_ban_gate_snapshot
from src.common.bot_runtime import load_plugins_for_role
from src.common.db import init_db
from src.common.logging import apply_stdlib_logging_channel_prefix
from src.common.shard.logs.process import install_shard_process_logging
from src.common.shard.registry import get_shard_registry
from src.common.shard.registry.config import get_shard_registry_settings
from src.common.shard.registry.listen_port import apply_listen_port
from src.common.utils.voice_downloader import ensure_voices
from src.common.web import install_nonebot_log_sink

apply_stdlib_logging_channel_prefix()
nonebot.init()
apply_listen_port(get_shard_registry_settings().hub_port)
install_shard_process_logging()
install_nonebot_log_sink()
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)


@driver.on_startup
async def startup():
    await init_db()
    await start_ban_gate_snapshot()
    reg = get_shard_registry()
    nonebot.logger.info(
        "bot_hub: registry hub_port={} worker_base_port={} shards={}",
        reg.hub_port,
        reg.worker_base_port,
        len(reg.shards),
    )
    await ensure_voices()
    try:
        from src.common.shard.logs.view import cleanup_stale_shard_log_files

        removed = cleanup_stale_shard_log_files()
        if removed:
            nonebot.logger.info("bot_hub: shard log cleanup: {}", removed)
    except Exception as e:
        nonebot.logger.warning("bot_hub: shard log cleanup failed: {}", e)


@driver.on_shutdown
async def shutdown():
    await stop_ban_gate_snapshot()


load_plugins_for_role()

if __name__ == "__main__":
    nonebot.run()
