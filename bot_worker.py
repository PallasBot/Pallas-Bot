"""Worker 分片进程入口：每进程约 5 个牛牛反向 WS。

启动前设置::

    PALLAS_SHARD_ENABLED=true
    PALLAS_BOT_ROLE=worker
    PALLAS_SHARD_ID=0
    PORT=8090
"""

import os

os.environ.setdefault("PALLAS_SHARD_ENABLED", "true")
os.environ.setdefault("PALLAS_BOT_ROLE", "worker")


def pin_worker_listen_port() -> None:
    """覆盖 .env 中 PORT，避免 getenv 读到首个 PORT 导致各 worker 抢同一端口。"""
    from src.common.shard.registry import get_shard_registry, worker_port_for_shard
    from src.common.shard.registry.config import get_shard_registry_settings
    from src.common.shard.registry.listen_port import apply_listen_port

    s = get_shard_registry_settings()
    port = worker_port_for_shard(s.shard_id, registry=get_shard_registry())
    apply_listen_port(port)


pin_worker_listen_port()

# ruff: noqa: E402
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from src.common.ban_gate.snapshot import start_ban_gate_snapshot, stop_ban_gate_snapshot
from src.common.bot_runtime import load_plugins_for_role
from src.common.db import init_db
from src.common.logging import apply_stdlib_logging_channel_prefix
from src.common.shard.logs.process import install_shard_process_logging
from src.common.shard.registry import get_shard_registry, worker_port_for_shard
from src.common.shard.registry.config import get_shard_registry_settings
from src.common.shard.registry.listen_port import apply_listen_port
from src.common.utils.voice_downloader import ensure_voices

apply_stdlib_logging_channel_prefix()
nonebot.init()
apply_listen_port(
    worker_port_for_shard(
        get_shard_registry_settings().shard_id,
        registry=get_shard_registry(),
    )
)
install_shard_process_logging()
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)


@driver.on_startup
async def startup():
    await init_db()
    await start_ban_gate_snapshot()
    s = get_shard_registry_settings()
    reg = get_shard_registry()
    port = worker_port_for_shard(s.shard_id, registry=reg)
    bots = reg.bots_on_shard(s.shard_id)
    nonebot.logger.info(
        "bot_worker: shard_id={} port={} assigned_bots={} (expect WS on this port)",
        s.shard_id,
        port,
        bots,
    )
    if int(os.environ.get("PORT", "0") or 0) not in (0, port):
        nonebot.logger.warning(
            "bot_worker: env PORT={} differs from registry port {} for shard {}",
            os.environ.get("PORT"),
            port,
            s.shard_id,
        )
    from src.common.shard.coord.worker_poll import start_shard_coord_worker_watcher

    start_shard_coord_worker_watcher()
    await ensure_voices()


@driver.on_shutdown
async def shutdown():
    await stop_ban_gate_snapshot()


load_plugins_for_role()

if __name__ == "__main__":
    nonebot.run()
