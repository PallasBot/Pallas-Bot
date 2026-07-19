"""跨部署入站抢占 Redis 实现。"""

from __future__ import annotations

from pallas.core.platform.federate.config import federate_redis_prefix
from pallas.core.platform.federate.redis_settings import federate_claim_ttl_sec, get_federate_redis_client


def federate_claim_redis_key(plugin: str, group_id: int, claim_key: int) -> str:
    prefix = federate_redis_prefix()
    return f"{prefix}:ingress:{plugin}:{group_id}:{claim_key}"


def read_federate_claim_owner_redis_sync(plugin: str, group_id: int, claim_key: int) -> str | None:
    client = get_federate_redis_client()
    if client is None:
        return None
    key = federate_claim_redis_key(plugin, group_id, claim_key)
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    owner = str(raw).strip()
    return owner or None


def try_claim_federate_message_redis_sync(
    plugin: str,
    group_id: int,
    claim_key: int,
    deployment_id: str,
) -> bool | None:
    """True/False 表示抢占结果；None 表示未走 Redis。"""
    client = get_federate_redis_client()
    if client is None:
        return None
    prefix = federate_redis_prefix()
    if not prefix:
        return None
    key = federate_claim_redis_key(plugin, group_id, claim_key)
    owner = deployment_id.strip().lower()
    if not owner:
        return False
    ttl = federate_claim_ttl_sec()
    try:
        if client.set(key, owner, nx=True, ex=ttl):
            return True
        existing = read_federate_claim_owner_redis_sync(plugin, group_id, claim_key)
        if existing is None:
            return False
        return existing.lower() == owner
    except Exception:
        return None
