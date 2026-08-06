"""联邦入站候选登记。"""

from __future__ import annotations

import os

from pallas.core.platform.federate.config import federate_redis_prefix
from pallas.core.platform.federate.redis_settings import get_federate_redis_client
from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key

CANDIDATE_TTL_SEC = max(1, int(os.getenv("PALLAS_FEDERATE_CANDIDATE_TTL_SEC", "2")))


def federate_ingress_candidate_redis_key(
    *,
    group_id: int,
    user_id: int,
    body: str,
    message_time: int,
    capability: str,
) -> str:
    prefix = federate_redis_prefix()
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        body,
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    return f"{prefix}:ingress_candidates:{int(group_id)}:{claim_key}"


def register_federate_ingress_candidate_sync(
    *,
    group_id: int,
    user_id: int,
    body: str,
    message_time: int,
    capability: str,
    bot_id: int,
) -> bool:
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    if client is None or not prefix or not capability:
        return False
    key = federate_ingress_candidate_redis_key(
        group_id=group_id,
        user_id=user_id,
        body=body,
        message_time=message_time,
        capability=capability,
    )
    try:
        client.sadd(key, f"{capability}:{int(bot_id)}")
        client.expire(key, CANDIDATE_TTL_SEC)
    except Exception:
        return False
    return True


def read_federate_ingress_candidate_bot_ids_sync(
    *,
    group_id: int,
    user_id: int,
    body: str,
    message_time: int,
    capability: str,
) -> frozenset[int]:
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    if client is None or not prefix:
        return frozenset()
    key = federate_ingress_candidate_redis_key(
        group_id=group_id,
        user_id=user_id,
        body=body,
        message_time=message_time,
        capability=capability,
    )
    try:
        raw_members = client.smembers(key)
    except Exception:
        return frozenset()
    members: set[int] = set()
    for raw in raw_members or ():
        value = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        _, _, raw_bot_id = value.partition(":")
        if raw_bot_id.isdigit():
            members.add(int(raw_bot_id))
    return frozenset(members)
