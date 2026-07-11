"""Worker 分片进程入口：每进程约 5 个牛牛反向 WS。

启动前设置::

    PALLAS_SHARD_ENABLED=true
    PALLAS_BOT_ROLE=worker
    PALLAS_SHARD_ID=0
    PORT=8090
"""

import asyncio
import os

os.environ.setdefault("PALLAS_SHARD_ENABLED", "true")
os.environ.setdefault("PALLAS_BOT_ROLE", "worker")

from pallas.core.foundation.config.dotenv import apply_repo_settings_to_environ

apply_repo_settings_to_environ()


def pin_worker_listen_port() -> None:
    """覆盖 .env 中 PORT，避免 getenv 读到首个 PORT 导致各 worker 抢同一端口。"""
    import json
    from pathlib import Path

    shard_id = int(os.environ.get("PALLAS_SHARD_ID", "0") or 0)
    port = int(os.environ.get("PORT", "0") or 0)
    reg_path = Path(__file__).resolve().parent / "data/pallas_shard/registry.json"
    if reg_path.is_file():
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8"))
            for row in data.get("shards") or []:
                if int(row.get("id", -1)) == shard_id:
                    port = int(row.get("port") or port)
                    break
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    if port > 0:
        os.environ["PORT"] = str(port)


pin_worker_listen_port()

# ruff: noqa: E402
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from pallas.console.web import install_nonebot_log_sink
from pallas.core.foundation.db import init_db
from pallas.core.foundation.logging import apply_stdlib_logging_channel_prefix
from pallas.core.foundation.startup_report import emit_startup_summary
from pallas.core.shared.adapters import register_onebot_v11_custom_events
from pallas.core.shared.utils.voice_downloader import ensure_voices
from pallas.product.ban_gate.snapshot import start_ban_gate_snapshot, stop_ban_gate_snapshot
from pallas.product.message_scrub import start_message_scrub_if_enabled

apply_stdlib_logging_channel_prefix()
nonebot.init()

from pallas.core.platform.bot_runtime import load_plugins_for_role
from pallas.core.platform.shard.logs.process import install_shard_process_logging
from pallas.core.platform.shard.registry import get_shard_registry, worker_port_for_shard
from pallas.core.platform.shard.registry.config import get_shard_registry_settings
from pallas.core.platform.shard.registry.listen_port import apply_listen_port

apply_listen_port(
    int(os.environ.get("PORT", "0") or 0)
    or worker_port_for_shard(
        get_shard_registry_settings().shard_id,
        registry=get_shard_registry(),
    )
)
start_message_scrub_if_enabled()
install_shard_process_logging()
install_nonebot_log_sink()
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
register_onebot_v11_custom_events()


async def _ensure_worker_voices_background() -> None:
    try:
        ok = await ensure_voices()
        if not ok:
            nonebot.logger.warning("bot_worker: voice ensure failed or incomplete")
    except Exception as err:
        nonebot.logger.warning("bot_worker: voice ensure failed: {}", err)


@driver.on_startup
async def startup():
    await init_db()
    from pallas.core.perm.migration import run_acl_startup_migrations

    try:
        await run_acl_startup_migrations()
    except Exception as e:
        nonebot.logger.warning("bot_worker: ACL startup migration failed: {}", e)
    await start_ban_gate_snapshot()
    from pallas.core.platform.coord.redis_settings import (
        coord_redis_enabled,
        ensure_coord_redis_ready_for_sharding,
        resolve_coord_redis_url,
    )
    from pallas.core.platform.shard.coord.worker_poll import start_shard_coord_worker_watcher

    ensure_coord_redis_ready_for_sharding()
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

    if coord_redis_enabled():
        nonebot.logger.info("bot_worker: cross-process claims via Redis ({})", resolve_coord_redis_url())
    start_shard_coord_worker_watcher()
    asyncio.create_task(_ensure_worker_voices_background(), name="worker_ensure_voices")


@driver.on_shutdown
async def shutdown():
    await stop_ban_gate_snapshot()


load_plugins_for_role()


@driver.on_startup
async def emit_startup_summary_on_startup():
    emit_startup_summary()


if __name__ == "__main__":
    nonebot.run()
