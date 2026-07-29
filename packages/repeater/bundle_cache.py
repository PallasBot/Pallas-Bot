"""复读候选短缓存，降低热群重复查库。"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

_CACHE: dict[str, tuple[float, Any]] = {}
_DEFAULT_TTL_SEC = 2.5
_MAX_ENTRIES = 4096


def repeater_bundle_cache_ttl_sec() -> float:
    raw = repo_env_raw_value("PALLAS_REPEATER_BUNDLE_CACHE_SEC")
    if raw is None:
        return _DEFAULT_TTL_SEC
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return _DEFAULT_TTL_SEC


def clear_repeater_bundle_cache_for_tests() -> None:
    _CACHE.clear()


def _cache_key(group_id: int, bot_id: int, raw_message: str, keywords: str) -> str:
    digest = hashlib.blake2b(
        f"{int(group_id)}|{int(bot_id)}|{raw_message}|{keywords}".encode(),
        digest_size=16,
    ).hexdigest()
    return digest


def get_cached_reply_bundle(group_id: int, bot_id: int, raw_message: str, keywords: str) -> Any | None:
    ttl = repeater_bundle_cache_ttl_sec()
    if ttl <= 0:
        return None
    key = _cache_key(group_id, bot_id, raw_message, keywords)
    hit = _CACHE.get(key)
    if hit is None:
        return None
    exp, value = hit
    if time.monotonic() >= exp:
        _CACHE.pop(key, None)
        return None
    return value


def store_cached_reply_bundle(
    group_id: int,
    bot_id: int,
    raw_message: str,
    keywords: str,
    bundle: Any,
) -> None:
    ttl = repeater_bundle_cache_ttl_sec()
    if ttl <= 0:
        return
    if len(_CACHE) >= _MAX_ENTRIES:
        # 简单淘汰：清一半过期或任意一半
        now = time.monotonic()
        stale = [k for k, (exp, _) in _CACHE.items() if exp <= now]
        for k in stale[: _MAX_ENTRIES // 2]:
            _CACHE.pop(k, None)
        if len(_CACHE) >= _MAX_ENTRIES:
            for k in list(_CACHE.keys())[: _MAX_ENTRIES // 4]:
                _CACHE.pop(k, None)
    key = _cache_key(group_id, bot_id, raw_message, keywords)
    _CACHE[key] = (time.monotonic() + ttl, bundle)
