"""分片：MAA getTask 轮询活跃时间。"""

from __future__ import annotations

import re
import threading
import time

from src.platform.shard.coord.coord_redis_store import coord_key, read_json_sync, setex_json_sync

_DEVICE_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_DEVICE_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

_lock = threading.Lock()
_local_seen: dict[tuple[str, str], float] = {}


def clear_seen_cache_for_tests() -> None:
    """测试用：清空进程内缓存。"""
    with _lock:
        _local_seen.clear()


def normalize_maa_device_id(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    compact = s.lower().replace("-", "")
    if _DEVICE_HEX32_RE.fullmatch(compact):
        return compact
    if _DEVICE_UUID_RE.fullmatch(s.lower()):
        return compact
    return None


def cache_key(user: str, device: str) -> tuple[str, str] | None:
    u = (user or "").strip()
    norm = normalize_maa_device_id(device)
    if not u or not norm:
        return None
    return u, norm


def _seen_redis_key(user: str, device: str) -> str | None:
    key = cache_key(user, device)
    if key is None:
        return None
    return coord_key("maa_seen", key[0], key[1])


def _seen_ttl_sec() -> int:
    from src.plugins.maa.config import get_maa_config

    return max(60, int(get_maa_config().maa_seen_ttl_seconds))


def flush_dirty_maa_seen_sync() -> None:
    """兼容清理脚本；Redis 模式下无需刷盘。"""
    return None


def touch_maa_seen_sync(user: str, device: str) -> None:
    key = cache_key(user, device)
    if key is None:
        return
    now = time.time()
    with _lock:
        _local_seen[key] = now
    redis_key = _seen_redis_key(user, device)
    if redis_key is None:
        return
    setex_json_sync(
        redis_key,
        {"user": key[0], "device": key[1], "seen_at": now},
        _seen_ttl_sec(),
    )


def was_maa_seen_sync(user: str, device: str, ttl: int) -> bool:
    key = cache_key(user, device)
    if key is None:
        return False
    ttl_sec = max(1, int(ttl))
    now = time.time()
    with _lock:
        local_at = _local_seen.get(key)
    if local_at and local_at > 0 and now - local_at <= ttl_sec:
        return True
    redis_key = _seen_redis_key(user, device)
    if redis_key is None:
        return False
    raw = read_json_sync(redis_key)
    if not raw:
        return False
    seen_at = float(raw.get("seen_at") or 0)
    if seen_at <= 0 or now - seen_at > ttl_sec:
        return False
    with _lock:
        if seen_at > _local_seen.get(key, 0.0):
            _local_seen[key] = seen_at
    return True
