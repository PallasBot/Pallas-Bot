"""全集群牛牛 QQ 集合。"""

from __future__ import annotations

import json
import threading

from src.foundation.paths import plugin_data_dir
from src.platform.shard import context as shard_ctx

_lock = threading.RLock()
_cached: frozenset[int] | None = None
# 本进程已连过 WS、但 accounts/registry 可能尚未刷新的 QQ
_session_connected: set[int] = set()

_PROTOCOL_PLUGIN = "pallas_protocol"
_ACCOUNTS_FILE = "accounts.json"


def invalidate_fleet_bot_cache() -> None:
    global _cached
    with _lock:
        _cached = None


def note_fleet_bot_session_connected(qq: int) -> None:
    """记录本进程新连接的牛牛，并刷新 fleet 缓存。"""
    global _cached
    with _lock:
        _session_connected.add(int(qq))
        _cached = None


def get_process_session_connected_ids() -> frozenset[int]:
    with _lock:
        return frozenset(_session_connected)


def get_catalog_bot_ids() -> frozenset[int]:
    """分片：全集群 catalog；单进程：block 维护的本进程已连接集合。"""
    if shard_ctx.sharding_active():
        return get_fleet_bot_ids()
    try:
        from src.plugins.block import plugin_config

        if plugin_config.bots:
            return frozenset(plugin_config.bots)
    except Exception:
        pass
    return frozenset()


def get_fleet_bot_ids() -> frozenset[int]:
    from src.platform.shard.data_sync import refresh_shard_data_caches_if_stale

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


def get_enabled_protocol_bot_ids() -> frozenset[int]:
    """协议端 accounts.json 中 enabled 的 QQ。"""
    return frozenset(_load_enabled_account_qq())


def _registry_qq_allowed(qq: int, *, enabled: set[int], session_extra: set[int]) -> bool:
    """registry 条目须对应协议 enabled 或曾连 WS，避免纯 registry 幽灵号进名册。"""
    return qq in enabled or qq in session_extra


def _load_fleet_bot_ids() -> set[int]:
    enabled = _load_enabled_account_qq()
    ids: set[int] = set(enabled)
    if shard_ctx.sharding_active():
        try:
            from src.platform.multi_bot.session_seen import load_cluster_session_seen_ids
            from src.platform.shard.registry.store import get_shard_registry

            reg = get_shard_registry()
            session_extra = set(load_cluster_session_seen_ids())
            with _lock:
                session_extra.update(_session_connected)

            def merge_reg_qq(raw: str) -> None:
                if not str(raw).isdigit():
                    return
                qq = int(raw)
                if _registry_qq_allowed(qq, enabled=enabled, session_extra=session_extra):
                    ids.add(qq)

            for key in reg.assignments:
                merge_reg_qq(str(key))
            for shard in reg.shards:
                for bid in shard.bot_ids:
                    merge_reg_qq(str(bid))
        except Exception:
            pass
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
