"""群级全实例禁用白名单：指定群可豁免 fleet 级禁用插件；落盘 data/help/group_fleet_whitelist.json。"""

from __future__ import annotations

import json
import time

from pallas.core.foundation.paths import plugin_data_dir

from .global_disable import GLOBAL_DISABLE_PROTECTED_PLUGINS

_FILE = "group_fleet_whitelist.json"
_REDIS_GEN_KEY = "pallas:help:group_fleet_whitelist_gen"
_REMOTE_GEN_SYNC_TTL_SEC = 2.0

_cache_mtime_ns: int | None = None
_cache_by_group: dict[int, frozenset[str]] = {}
_synced_redis_gen: int = -1
_remote_gen_checked_at: float = 0.0


def group_fleet_whitelist_path():
    return plugin_data_dir("help") / _FILE


def invalidate_group_fleet_whitelist_cache() -> None:
    global _cache_mtime_ns, _cache_by_group, _remote_gen_checked_at
    _cache_mtime_ns = None
    _cache_by_group = {}
    _remote_gen_checked_at = 0.0


def file_mtime_ns(path) -> int:
    if not path.exists():
        return 0
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _normalize_plugins(plugins: list[str]) -> list[str]:
    protected = GLOBAL_DISABLE_PROTECTED_PLUGINS
    return sorted({str(x).strip() for x in plugins if str(x).strip() and str(x).strip() not in protected})


def _read_whitelist_from_disk() -> dict[int, frozenset[str]]:
    path = group_fleet_whitelist_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    groups = raw.get("groups", {})
    if not isinstance(groups, dict):
        return {}
    out: dict[int, frozenset[str]] = {}
    for key, vals in groups.items():
        try:
            group_id = int(key)
        except (TypeError, ValueError):
            continue
        if group_id <= 0 or not isinstance(vals, list):
            continue
        plugins = _normalize_plugins(vals)
        if plugins:
            out[group_id] = frozenset(plugins)
    return out


def bump_group_fleet_whitelist_remote_generation() -> None:
    try:
        from pallas.core.platform.coord.redis_claim import get_coord_redis_client

        client = get_coord_redis_client()
        if client is not None:
            client.incr(_REDIS_GEN_KEY)
    except Exception:
        pass


def sync_group_fleet_whitelist_remote_generation() -> bool:
    """对比 Redis 世代；变化时清空进程内缓存。返回是否发生变化。"""
    global _synced_redis_gen, _remote_gen_checked_at
    now = time.monotonic()
    if _remote_gen_checked_at and now - _remote_gen_checked_at < _REMOTE_GEN_SYNC_TTL_SEC:
        return False
    try:
        from pallas.core.platform.coord.redis_claim import get_coord_redis_client

        client = get_coord_redis_client()
        if client is None:
            _remote_gen_checked_at = now
            return False
        raw = client.get(_REDIS_GEN_KEY)
        _remote_gen_checked_at = now
        remote = int(raw) if raw else 0
        if remote == _synced_redis_gen:
            return False
        _synced_redis_gen = remote
        invalidate_group_fleet_whitelist_cache()
        _remote_gen_checked_at = now
        return True
    except Exception:
        _remote_gen_checked_at = now
        return False


def resolve_group_fleet_whitelist_map() -> dict[int, frozenset[str]]:
    """进程内缓存 + mtime 校验；热路径仅 stat，文件未变时不读 JSON。"""
    sync_group_fleet_whitelist_remote_generation()
    global _cache_mtime_ns, _cache_by_group
    path = group_fleet_whitelist_path()
    mtime_ns = file_mtime_ns(path)
    if _cache_mtime_ns is not None and mtime_ns == _cache_mtime_ns:
        return _cache_by_group
    data = _read_whitelist_from_disk()
    _cache_mtime_ns = mtime_ns
    _cache_by_group = data
    return data


def resolve_group_fleet_whitelist_plugins(group_id: int | None) -> frozenset[str]:
    if not group_id:
        return frozenset()
    return resolve_group_fleet_whitelist_map().get(int(group_id), frozenset())


def load_group_fleet_whitelist() -> list[dict[str, object]]:
    data = resolve_group_fleet_whitelist_map()
    return [{"group_id": gid, "plugins": sorted(names)} for gid, names in sorted(data.items())]


def add_group_fleet_whitelist_plugin(group_id: int, plugin_name: str) -> bool:
    """将插件加入指定群的全实例禁用白名单；已存在则 no-op。返回是否写入变更。"""
    try:
        gid = int(group_id)
    except (TypeError, ValueError):
        return False
    if gid <= 0:
        return False
    plugins = _normalize_plugins([plugin_name])
    if not plugins:
        return False
    name = plugins[0]
    current = resolve_group_fleet_whitelist_map()
    if name in current.get(gid, frozenset()):
        return False
    merged: dict[int, set[str]] = {g: set(names) for g, names in current.items()}
    merged.setdefault(gid, set()).add(name)
    save_group_fleet_whitelist([{"group_id": g, "plugins": sorted(names)} for g, names in sorted(merged.items())])
    return True


def save_group_fleet_whitelist(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    global _cache_mtime_ns, _cache_by_group, _synced_redis_gen, _remote_gen_checked_at
    merged: dict[int, set[str]] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        raw_gid = item.get("group_id")
        raw_plugins = item.get("plugins", [])
        try:
            group_id = int(raw_gid)
        except (TypeError, ValueError):
            continue
        if group_id <= 0 or not isinstance(raw_plugins, list):
            continue
        plugins = _normalize_plugins(raw_plugins)
        if not plugins:
            continue
        merged.setdefault(group_id, set()).update(plugins)
    groups_json = {str(gid): sorted(names) for gid, names in sorted(merged.items())}
    path = group_fleet_whitelist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"groups": groups_json}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    data = {gid: frozenset(names) for gid, names in merged.items()}
    _cache_mtime_ns = file_mtime_ns(path)
    _cache_by_group = data
    bump_group_fleet_whitelist_remote_generation()
    try:
        from pallas.core.platform.coord.redis_claim import get_coord_redis_client

        client = get_coord_redis_client()
        if client is not None:
            raw = client.get(_REDIS_GEN_KEY)
            _synced_redis_gen = int(raw) if raw else _synced_redis_gen
            _remote_gen_checked_at = time.monotonic()
    except Exception:
        pass
    return [{"group_id": gid, "plugins": sorted(names)} for gid, names in sorted(merged.items())]
