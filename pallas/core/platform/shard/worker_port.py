"""分片 worker 本进程 HTTP 监听端口。"""

from __future__ import annotations

from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.registry.config import get_shard_registry_settings
from pallas.core.platform.shard.registry.store import worker_port_for_shard


def current_worker_port() -> int | None:
    if not shard_ctx.sharding_active():
        return None
    s = get_shard_registry_settings()
    if s.role != "worker":
        return None
    return int(worker_port_for_shard(int(s.shard_id)))
