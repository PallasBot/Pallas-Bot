"""hosted/dream gate 热路径上的短时 Redis 读缓存。"""

from __future__ import annotations

import os
import threading
import time
from typing import TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}


def gate_read_cache_ttl_sec() -> float:
    raw = (os.environ.get("PALLAS_GATE_READ_CACHE_MS") or "1500").strip()
    try:
        ms = float(raw)
    except ValueError:
        ms = 1500.0
    return max(0.05, ms / 1000.0)


def gate_read_cache_key_owned(plugin: str, group_id: int) -> str:
    return f"owned:{plugin}:{int(group_id)}"


def gate_read_cache_key_activity(namespace: str, group_id: int) -> str:
    return f"activity:{namespace}:{int(group_id)}"


def gate_read_cache_get[T](key: str, loader, *, ttl_sec: float | None = None) -> T:
    ttl = gate_read_cache_ttl_sec() if ttl_sec is None else max(0.05, float(ttl_sec))
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]  # type: ignore[return-value]
    value = loader()
    expires = now + ttl
    with _lock:
        _cache[key] = (expires, value)
    return value


def gate_read_cache_invalidate(*keys: str) -> None:
    if not keys:
        return
    with _lock:
        for key in keys:
            _cache.pop(key, None)


def gate_read_cache_invalidate_prefix(prefix: str) -> None:
    if not prefix:
        return
    with _lock:
        drop = [k for k in _cache if k.startswith(prefix)]
        for key in drop:
            _cache.pop(key, None)


def reset_gate_read_cache_for_tests() -> None:
    with _lock:
        _cache.clear()
