"""分片共享 data：按 registry / accounts 文件 mtime 失效各进程内存缓存。"""

from __future__ import annotations

import threading

from src.common.paths import plugin_data_dir
from src.common.shard.registry.config import is_sharding_active

_lock = threading.Lock()
_seen: tuple[float, float] | None = None

_REGISTRY_PLUGIN = "pallas_shard"
_ACCOUNTS_PLUGIN = "pallas_protocol"
_ACCOUNTS_FILE = "accounts.json"
_REGISTRY_FILE = "registry.json"


def _file_mtime(path) -> float:
    try:
        return path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        return 0.0


def _current_mtuples() -> tuple[float, float]:
    reg = plugin_data_dir(_REGISTRY_PLUGIN, create=False) / _REGISTRY_FILE
    acc = plugin_data_dir(_ACCOUNTS_PLUGIN, create=False) / _ACCOUNTS_FILE
    return (_file_mtime(reg), _file_mtime(acc))


def refresh_shard_data_caches_if_stale() -> bool:
    """若共享 JSON 已变更则失效 fleet / registry 缓存；返回是否发生过失效。"""
    if not is_sharding_active():
        return False
    cur = _current_mtuples()
    global _seen
    with _lock:
        if _seen == cur:
            return False
        _seen = cur
    from src.common.multi_bot.fleet import invalidate_fleet_bot_cache
    from src.common.shard.registry.store import clear_shard_registry_cache

    invalidate_fleet_bot_cache()
    clear_shard_registry_cache()
    return True
