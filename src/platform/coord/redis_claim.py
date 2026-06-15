"""跨进程 message claim：Redis SET NX。"""

from __future__ import annotations

from functools import lru_cache

from src.platform.coord.redis_settings import (
    coord_redis_claim_ttl_sec,
    coord_redis_enabled,
    resolve_coord_redis_url,
)

_KEY_PREFIX = "pallas:msg_claim:"


def claim_redis_key(plugin: str, group_id: int, message_id: int) -> str:
    return f"{_KEY_PREFIX}{plugin}:{group_id}:{message_id}"


@lru_cache(maxsize=1)
def get_coord_redis_client():
    if not coord_redis_enabled():
        return None
    url = resolve_coord_redis_url()
    if not url:
        return None
    try:
        import redis
    except ImportError:
        return None
    return redis.Redis.from_url(url, socket_connect_timeout=1.0, socket_timeout=2.0)


def clear_coord_redis_client_cache() -> None:
    get_coord_redis_client.cache_clear()


def read_claim_owner_redis_sync(plugin: str, group_id: int, message_id: int) -> int | None:
    """Redis 中已有 owner 时返回 QQ/shard_id；未启用或不存在时返回 None。"""
    client = get_coord_redis_client()
    if client is None:
        return None
    key = claim_redis_key(plugin, group_id, message_id)
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def take_claim_message_redis_sync(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool | None:
    """覆盖 Redis claim。None 表示未走 Redis。"""
    client = get_coord_redis_client()
    if client is None:
        return None
    key = claim_redis_key(plugin, group_id, message_id)
    ttl = coord_redis_claim_ttl_sec()
    owner = str(int(bot_id))
    try:
        client.set(key, owner, ex=ttl)
        return True
    except Exception:
        return None


def try_claim_message_redis_sync(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool | None:
    """
    尝试 Redis 抢占。

    返回 True/False 表示结果；None 表示未走 Redis。
    """
    client = get_coord_redis_client()
    if client is None:
        return None
    key = claim_redis_key(plugin, group_id, message_id)
    ttl = coord_redis_claim_ttl_sec()
    owner = str(int(bot_id))
    try:
        if client.set(key, owner, nx=True, ex=ttl):
            return True
        existing = read_claim_owner_redis_sync(plugin, group_id, message_id)
        if existing is None:
            return False
        return existing == int(bot_id)
    except Exception:
        return None
