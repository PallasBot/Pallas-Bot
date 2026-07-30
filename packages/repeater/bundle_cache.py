"""复读候选短缓存：命中结果 + 空结果（负缓存），降低热群重复查库。

空结果占多数时，负缓存跨同群多号共享（不含 bot_id），正命中仍按 bot 隔离。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

_CACHE: dict[str, tuple[float, Any]] = {}
_NEGATIVE = object()
_DEFAULT_HIT_TTL_SEC = 8.0
_DEFAULT_NEGATIVE_TTL_SEC = 20.0
_MAX_ENTRIES = 8192


def repeater_bundle_cache_ttl_sec() -> float:
    """正命中 TTL；``0`` 关闭正缓存。"""
    raw = repo_env_raw_value("PALLAS_REPEATER_BUNDLE_CACHE_SEC")
    if raw is None:
        return _DEFAULT_HIT_TTL_SEC
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return _DEFAULT_HIT_TTL_SEC


def repeater_bundle_negative_cache_ttl_sec() -> float:
    """空结果 / 跳过查库的负缓存 TTL；``0`` 关闭负缓存。"""
    raw = repo_env_raw_value("PALLAS_REPEATER_BUNDLE_NEGATIVE_CACHE_SEC")
    if raw is None:
        return _DEFAULT_NEGATIVE_TTL_SEC
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return _DEFAULT_NEGATIVE_TTL_SEC


def clear_repeater_bundle_cache_for_tests() -> None:
    _CACHE.clear()


def _cache_key(group_id: int, bot_id: int, raw_message: str, keywords: str) -> str:
    digest = hashlib.blake2b(
        f"{int(group_id)}|{int(bot_id)}|{raw_message}|{keywords}".encode(),
        digest_size=16,
    ).hexdigest()
    return digest


def _shared_negative_key(group_id: int, raw_message: str, keywords: str) -> str:
    digest = hashlib.blake2b(
        f"neg|{int(group_id)}|{raw_message}|{keywords}".encode(),
        digest_size=16,
    ).hexdigest()
    return digest


def _prune_if_needed() -> None:
    if len(_CACHE) < _MAX_ENTRIES:
        return
    now = time.monotonic()
    stale = [k for k, (exp, _) in _CACHE.items() if exp <= now]
    for k in stale[: _MAX_ENTRIES // 2]:
        _CACHE.pop(k, None)
    if len(_CACHE) >= _MAX_ENTRIES:
        for k in list(_CACHE.keys())[: _MAX_ENTRIES // 4]:
            _CACHE.pop(k, None)


def _read_entry(key: str) -> tuple[bool, Any | None] | None:
    """Return None if absent/expired; else (is_negative, bundle_or_none)."""
    hit = _CACHE.get(key)
    if hit is None:
        return None
    exp, value = hit
    if time.monotonic() >= exp:
        _CACHE.pop(key, None)
        return None
    if value is _NEGATIVE:
        return True, None
    return False, value


def lookup_cached_reply_bundle(
    group_id: int,
    bot_id: int,
    raw_message: str,
    keywords: str,
) -> tuple[bool, bool, Any | None]:
    """查缓存。

    Returns:
        (hit, negative, bundle)
        - hit=False: 未命中，需查库
        - hit=True, negative=True, bundle=None: 负缓存（已确认无候选）
        - hit=True, negative=False, bundle=...: 正命中
    """
    if repeater_bundle_cache_ttl_sec() <= 0 and repeater_bundle_negative_cache_ttl_sec() <= 0:
        return False, False, None

    bot_key = _cache_key(group_id, bot_id, raw_message, keywords)
    got = _read_entry(bot_key)
    if got is not None:
        is_neg, bundle = got
        return True, is_neg, bundle

    if repeater_bundle_negative_cache_ttl_sec() <= 0:
        return False, False, None
    shared = _read_entry(_shared_negative_key(group_id, raw_message, keywords))
    if shared is not None and shared[0]:
        return True, True, None
    return False, False, None


def get_cached_reply_bundle(group_id: int, bot_id: int, raw_message: str, keywords: str) -> Any | None:
    """兼容旧调用：仅返回正命中的 bundle；负缓存视为未命中。"""
    hit, negative, bundle = lookup_cached_reply_bundle(group_id, bot_id, raw_message, keywords)
    if hit and not negative:
        return bundle
    return None


def store_cached_reply_bundle(
    group_id: int,
    bot_id: int,
    raw_message: str,
    keywords: str,
    bundle: Any,
) -> None:
    """写入正命中；``bundle is None`` 时请改用 ``store_cached_reply_miss``。"""
    ttl = repeater_bundle_cache_ttl_sec()
    if ttl <= 0 or bundle is None:
        return
    _prune_if_needed()
    key = _cache_key(group_id, bot_id, raw_message, keywords)
    _CACHE[key] = (time.monotonic() + ttl, bundle)


def store_cached_reply_miss(
    group_id: int,
    bot_id: int,
    raw_message: str,
    keywords: str,
) -> None:
    """空结果负缓存：同群多号共享，避免每人各打一轮 PG。"""
    ttl = repeater_bundle_negative_cache_ttl_sec()
    if ttl <= 0:
        return
    _prune_if_needed()
    now = time.monotonic()
    exp = now + ttl
    shared = _shared_negative_key(group_id, raw_message, keywords)
    _CACHE[shared] = (exp, _NEGATIVE)
    # 本号也记一份，避免与旧正键冲突时还去查库
    bot_key = _cache_key(group_id, bot_id, raw_message, keywords)
    _CACHE[bot_key] = (exp, _NEGATIVE)
