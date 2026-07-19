"""分片共享 data：按 registry / accounts 文件 mtime 失效各进程内存缓存。"""

from __future__ import annotations

import threading

from pallas.core.platform.shard import context as shard_ctx

_lock = threading.Lock()
_seen: tuple[float, float] | None = None

_REGISTRY_PLUGIN = "pallas_shard"
_REGISTRY_FILE = "registry.json"


def _file_mtime(path) -> float:
    try:
        return path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        return 0.0


def _current_mtuples() -> tuple[float, float]:
    from pallas.core.foundation.paths import plugin_data_dir
    from pallas.core.platform.protocol_paths import protocol_accounts_path

    reg = plugin_data_dir(_REGISTRY_PLUGIN, create=False) / _REGISTRY_FILE
    acc = protocol_accounts_path()
    return (_file_mtime(reg), _file_mtime(acc))


def refresh_shard_data_caches_if_stale() -> bool:
    """若共享 JSON 已变更则失效 fleet / registry 缓存；返回是否发生过失效。"""
    if not shard_ctx.sharding_active():
        return False
    cur = _current_mtuples()
    global _seen
    with _lock:
        if _seen == cur:
            return False
        _seen = cur
    from pallas.core.platform.multi_bot.fleet import invalidate_fleet_bot_cache
    from pallas.core.platform.shard.registry.store import clear_shard_registry_cache

    invalidate_fleet_bot_cache()
    clear_shard_registry_cache()
    return True
