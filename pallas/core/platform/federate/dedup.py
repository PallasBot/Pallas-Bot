"""跨部署群消息入站抢占。"""

from __future__ import annotations

import asyncio

from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key, cross_bot_message_signature

_CROSS_FEDERATE_CLAIM_MAX = 4000
_cross_federate_claim_lock = asyncio.Lock()
_cross_federate_claim_owners: dict[tuple[str, tuple[int, int, str] | tuple[int, int, str, int]], str] = {}


def _prune_federate_claims() -> None:
    if len(_cross_federate_claim_owners) <= _CROSS_FEDERATE_CLAIM_MAX:
        return
    for key in list(_cross_federate_claim_owners.keys())[: _CROSS_FEDERATE_CLAIM_MAX // 2]:
        _cross_federate_claim_owners.pop(key, None)


async def try_claim_cross_federate_message_memory(
    plugin: str,
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    deployment_id: str,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
) -> bool:
    sig = cross_bot_message_signature(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    owner = deployment_id.strip().lower()
    if not owner:
        return False
    key = (plugin, sig)
    async with _cross_federate_claim_lock:
        existing = _cross_federate_claim_owners.get(key)
        if existing is None:
            _cross_federate_claim_owners[key] = owner
            _prune_federate_claims()
            return True
        return existing == owner


async def try_claim_cross_federate_message(
    plugin: str,
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    deployment_id: str,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
) -> bool:
    """同 federate 池跨 deployment：仅一个 deployment 通过 ingress。"""
    from pallas.core.platform.federate.config import federate_ingress_active

    if not federate_ingress_active():
        return True
    if not await try_claim_cross_federate_message_memory(
        plugin,
        group_id,
        user_id,
        message_body,
        message_time,
        deployment_id,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    ):
        return False
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    from pallas.core.platform.federate.redis_claim import try_claim_federate_message_redis_sync

    redis_result = await asyncio.to_thread(
        try_claim_federate_message_redis_sync,
        plugin,
        group_id,
        claim_key,
        deployment_id,
    )
    if redis_result is None:
        return False
    return redis_result
