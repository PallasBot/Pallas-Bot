"""全实例运行时禁用插件。"""

from __future__ import annotations

import json
import time

from pallas.core.foundation.paths import plugin_data_dir

from .visibility import BUILTIN_HELP_HIDDEN_PLUGINS

_PROTECTED_EXTRA = frozenset({
    "help",
    "ingress_gate",
})

GLOBAL_DISABLE_PROTECTED_PLUGINS = frozenset(sorted(BUILTIN_HELP_HIDDEN_PLUGINS | _PROTECTED_EXTRA))

_FILE = "global_disabled_plugins.json"
_STORAGE_KEY = "global_disabled_plugins"
_REDIS_GEN_KEY = "pallas:help:global_disable_gen"
_REMOTE_GEN_SYNC_TTL_SEC = 2.0

_cache_mtime_ns: int | None = None
_cache_names: frozenset[str] = frozenset()
_synced_redis_gen: int = -1
_remote_gen_checked_at: float = 0.0


def global_disabled_plugins_path():
    from pallas.core.storage.deploy_store import deploy_storage_path

    return deploy_storage_path("help")


def _legacy_global_disable_path():
    return plugin_data_dir("help") / _FILE


def invalidate_global_disabled_cache() -> None:
    global _cache_mtime_ns, _cache_names, _remote_gen_checked_at
    _cache_mtime_ns = None
    _cache_names = frozenset()
    _remote_gen_checked_at = 0.0


def file_mtime_ns(path) -> int:
    if not path.exists():
        return 0
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _read_disabled_names_from_disk() -> frozenset[str]:
    from pallas.core.storage.deploy_store import DeployPluginStorage

    protected = GLOBAL_DISABLE_PROTECTED_PLUGINS
    try:
        store = DeployPluginStorage("help")
        raw = store.get(_STORAGE_KEY)
        if raw is None:
            return _migrate_legacy_global_disabled()
        if not isinstance(raw, list):
            return frozenset()
        return frozenset(str(x).strip() for x in raw if str(x).strip() and str(x).strip() not in protected)
    except Exception:
        return _read_legacy_global_disabled()


def _read_legacy_global_disabled() -> frozenset[str]:
    path = _legacy_global_disable_path()
    if not path.exists():
        return frozenset()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return frozenset()
    if not isinstance(raw, dict):
        return frozenset()
    vals = raw.get("disabled_plugins", [])
    if not isinstance(vals, list):
        return frozenset()
    protected = GLOBAL_DISABLE_PROTECTED_PLUGINS
    return frozenset(str(x).strip() for x in vals if str(x).strip() and str(x).strip() not in protected)


def _migrate_legacy_global_disabled() -> frozenset[str]:
    names = _read_legacy_global_disabled()
    path = _legacy_global_disable_path()
    if not names and not path.exists():
        return frozenset()
    from pallas.core.storage.deploy_store import DeployPluginStorage

    DeployPluginStorage("help").set(_STORAGE_KEY, sorted(names))
    if path.exists():
        backup = path.with_suffix(path.suffix + ".migrated")
        if not backup.exists():
            path.replace(backup)
    return names


def bump_global_disable_remote_generation() -> None:
    try:
        from pallas.core.platform.coord.redis_claim import get_coord_redis_client

        client = get_coord_redis_client()
        if client is not None:
            client.incr(_REDIS_GEN_KEY)
    except Exception:
        pass


def sync_global_disable_remote_generation() -> bool:
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
        invalidate_global_disabled_cache()
        _remote_gen_checked_at = now
        return True
    except Exception:
        _remote_gen_checked_at = now
        return False


def resolve_global_disabled_plugin_names() -> frozenset[str]:
    """进程内缓存 + mtime 校验；热路径仅 stat，文件未变时不读 JSON。"""
    sync_global_disable_remote_generation()
    global _cache_mtime_ns, _cache_names
    path = global_disabled_plugins_path()
    mtime_ns = file_mtime_ns(path)
    if _cache_mtime_ns is not None and mtime_ns == _cache_mtime_ns:
        return _cache_names
    names = _read_disabled_names_from_disk()
    _cache_mtime_ns = mtime_ns
    _cache_names = names
    return names


def load_global_disabled_plugins() -> list[str]:
    return sorted(resolve_global_disabled_plugin_names())


def save_global_disabled_plugins(disabled_plugins: list[str]) -> list[str]:
    global _cache_mtime_ns, _cache_names, _synced_redis_gen, _remote_gen_checked_at
    protected = GLOBAL_DISABLE_PROTECTED_PLUGINS
    out = sorted({str(x).strip() for x in disabled_plugins if str(x).strip() and str(x).strip() not in protected})
    from pallas.core.storage.deploy_store import DeployPluginStorage

    DeployPluginStorage("help").set(_STORAGE_KEY, out)
    names = frozenset(out)
    _cache_mtime_ns = file_mtime_ns(global_disabled_plugins_path())
    _cache_names = names
    bump_global_disable_remote_generation()
    try:
        from pallas.core.platform.coord.redis_claim import get_coord_redis_client

        client = get_coord_redis_client()
        if client is not None:
            raw = client.get(_REDIS_GEN_KEY)
            _synced_redis_gen = int(raw) if raw else _synced_redis_gen
            _remote_gen_checked_at = time.monotonic()
    except Exception:
        pass
    return out


def is_global_disable_protected(package: str) -> bool:
    return (package or "").strip() in GLOBAL_DISABLE_PROTECTED_PLUGINS
