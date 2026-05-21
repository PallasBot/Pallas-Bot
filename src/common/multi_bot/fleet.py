"""全集群牛牛 QQ 集合（分片时 block / ingress 须识别其它 worker 上的牛）。"""

from __future__ import annotations

import json
import threading

from src.common.paths import plugin_data_dir
from src.common.shard.registry.config import is_sharding_active

_lock = threading.RLock()
_cached: frozenset[int] | None = None
# 本进程已连过 WS、但 accounts/registry 可能尚未刷新的 QQ（分片 reload 时并入）
_session_connected: set[int] = set()

_PROTOCOL_PLUGIN = "pallas_protocol"
_ACCOUNTS_FILE = "accounts.json"


def invalidate_fleet_bot_cache() -> None:
    global _cached
    with _lock:
        _cached = None


def note_fleet_bot_session_connected(qq: int) -> None:
    """记录本进程新连接的牛牛，并刷新 fleet 缓存（供 block / bot_status 等）。"""
    global _cached
    with _lock:
        _session_connected.add(int(qq))
        _cached = None


def get_catalog_bot_ids() -> frozenset[int]:
    """分片：全集群 catalog；单进程：block 维护的本进程已连接集合。"""
    if is_sharding_active():
        return get_fleet_bot_ids()
    try:
        from src.plugins.block import plugin_config

        if plugin_config.bots:
            return frozenset(plugin_config.bots)
    except Exception:
        pass
    return frozenset()


def get_fleet_bot_ids() -> frozenset[int]:
    from src.common.shard.data_sync import refresh_shard_data_caches_if_stale

    refresh_shard_data_caches_if_stale()
    global _cached
    with _lock:
        if _cached is not None:
            return _cached
        _cached = frozenset(_load_fleet_bot_ids())
        return _cached


def fleet_bot_ids_contains(qq: int | str) -> bool:
    try:
        return int(qq) in get_fleet_bot_ids()
    except (TypeError, ValueError):
        return False


def _load_fleet_bot_ids() -> set[int]:
    ids: set[int] = set()
    if is_sharding_active():
        try:
            from src.common.shard.registry.store import get_shard_registry

            reg = get_shard_registry()
            for key in reg.assignments:
                if str(key).isdigit():
                    ids.add(int(key))
            for shard in reg.shards:
                for bid in shard.bot_ids:
                    if str(bid).isdigit():
                        ids.add(int(bid))
        except Exception:
            pass
    ids.update(_load_enabled_account_qq())
    if is_sharding_active():
        with _lock:
            ids.update(_session_connected)
    return ids


def _load_enabled_account_qq() -> set[int]:
    path = plugin_data_dir(_PROTOCOL_PLUGIN) / _ACCOUNTS_FILE
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(raw, dict):
        return set()
    out: set[int] = set()
    for aid, acc in raw.items():
        if not isinstance(acc, dict):
            continue
        if acc.get("enabled") is False:
            continue
        qq = acc.get("qq") or acc.get("id") or aid
        if str(qq).isdigit():
            out.add(int(qq))
    return out
