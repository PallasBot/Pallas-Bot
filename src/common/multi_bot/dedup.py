"""? Bot ???????????????? claim ????????"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass, field

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from src.common.multi_bot.claim import try_claim_message

_DEDUP_SHARDS = 32
_GROUP_EVENT_DEDUP_MAX = 4000
_GROUP_EVENT_DEDUP_PER_SHARD = max(64, _GROUP_EVENT_DEDUP_MAX // _DEDUP_SHARDS)

_CROSS_BOT_CLAIM_MAX = 4000
_CROSS_BOT_CLAIM_PER_SHARD = max(64, _CROSS_BOT_CLAIM_MAX // _DEDUP_SHARDS)

ClaimKey = tuple[str, tuple[int, int, str]]
GroupEventSig = tuple[int, int, str, int]


def _shard_index(group_id: int) -> int:
    return int(group_id) % _DEDUP_SHARDS


@dataclass
class _GroupEventDedupShard:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    order: deque[GroupEventSig] = field(default_factory=deque)
    sig_set: set[GroupEventSig] = field(default_factory=set)


@dataclass
class _CrossBotClaimShard:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    owners: dict[ClaimKey, int] = field(default_factory=dict)
    order: deque[ClaimKey] = field(default_factory=deque)


_group_event_shards = tuple(_GroupEventDedupShard() for _ in range(_DEDUP_SHARDS))
_cross_bot_claim_shards = tuple(_CrossBotClaimShard() for _ in range(_DEDUP_SHARDS))


def normalize_group_raw_message(raw_message: str) -> str:
    # ? ChatData / learn ????? image ???????????
    return re.sub(r"\.image,.+?\]", ".image]", raw_message)


def normalize_group_plaintext(plaintext: str) -> str:
    return re.sub(r"\s+", " ", plaintext.strip())


def normalize_message_time(message_time: int) -> int:
    t = int(message_time)
    if t > 10_000_000_000:
        return t // 1000
    return t


def cross_bot_message_signature(
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    *,
    use_plaintext: bool = True,
) -> tuple[int, int, str]:
    """????????? + ?? + ???????? event.time??"""
    del message_time
    body = normalize_group_plaintext(message_body) if use_plaintext else normalize_group_raw_message(message_body)
    return (group_id, user_id, body)


def cross_bot_group_message_key(
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    *,
    use_plaintext: bool = True,
) -> int:
    """? Bot ??? message_id?? + ?? + ????????"""
    sig = cross_bot_message_signature(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
    )
    payload = f"{sig[0]}:{sig[1]}:{sig[2]}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:15], 16)


def _cross_bot_claim_touch(shard: _CrossBotClaimShard, key: ClaimKey, bot_id: int) -> None:
    """????? shard????? LRU ??????"""
    shard.owners[key] = bot_id
    shard.order.append(key)
    while len(shard.order) > _CROSS_BOT_CLAIM_PER_SHARD:
        old = shard.order.popleft()
        if shard.owners.get(old) is not None:
            shard.owners.pop(old, None)


async def try_claim_cross_bot_message_memory(
    plugin: str,
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    bot_id: int,
    *,
    use_plaintext: bool = True,
) -> bool:
    sig = cross_bot_message_signature(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
    )
    key = (plugin, sig)
    shard = _cross_bot_claim_shards[_shard_index(group_id)]
    async with shard.lock:
        owner = shard.owners.get(key)
        if owner is None:
            _cross_bot_claim_touch(shard, key, bot_id)
            return True
        return owner == bot_id


async def try_claim_cross_bot_message(
    plugin: str,
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    bot_id: int,
    *,
    use_plaintext: bool = True,
) -> bool:
    """???? + ????? claim?data/ ? .claim??"""
    if not await try_claim_cross_bot_message_memory(
        plugin,
        group_id,
        user_id,
        message_body,
        message_time,
        bot_id,
        use_plaintext=use_plaintext,
    ):
        return False
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
    )
    return await try_claim_message(plugin, group_id, claim_key, bot_id)


async def should_skip_duplicate_group_event(
    group_id: int,
    user_id: int,
    norm_raw: str,
    message_time: int,
) -> bool:
    sig = (group_id, user_id, norm_raw, normalize_message_time(message_time))
    shard = _group_event_shards[_shard_index(group_id)]
    async with shard.lock:
        if sig in shard.sig_set:
            return True
        while len(shard.order) >= _GROUP_EVENT_DEDUP_PER_SHARD:
            old = shard.order.popleft()
            shard.sig_set.discard(old)
        shard.order.append(sig)
        shard.sig_set.add(sig)
        return False


_GROUP_GATE_LOCK = asyncio.Lock()
_owned_gate: dict[tuple[str, int], tuple[int, float]] = {}
_broadcast_slot_until: dict[tuple[str, int], float] = {}


async def try_begin_group_owned_gate(
    plugin: str,
    group_id: int,
    bot_id: int,
    *,
    gate_sec: float,
) -> bool:
    """????????? gate ? bot ? TTL ??????????? bot ???"""
    ttl = max(1.0, float(gate_sec))
    now = time.time()
    key = (plugin, group_id)
    async with _GROUP_GATE_LOCK:
        rec = _owned_gate.get(key)
        if rec is not None:
            owner, until = rec
            if now < until:
                return owner == bot_id
        _owned_gate[key] = (bot_id, now + ttl)
        if len(_owned_gate) > 2000:
            expired = [k for k, (_, u) in _owned_gate.items() if u <= now]
            for k in expired:
                _owned_gate.pop(k, None)
        return True


async def try_acquire_group_broadcast_slot(
    plugin: str,
    group_id: int,
    *,
    ttl_sec: float = 3.0,
) -> bool:
    """?????????????? True?TTL ??? bot ?? False?"""
    ttl = max(0.1, float(ttl_sec))
    now = time.time()
    key = (plugin, group_id)
    async with _GROUP_GATE_LOCK:
        until = _broadcast_slot_until.get(key, 0.0)
        if now < until:
            return False
        _broadcast_slot_until[key] = now + ttl
        if len(_broadcast_slot_until) > 2000:
            expired = [k for k, u in _broadcast_slot_until.items() if u <= now]
            for k in expired:
                _broadcast_slot_until.pop(k, None)
        return True


async def try_begin_group_draw_cheer(group_id: int, bot_id: int, *, gate_sec: float) -> bool:
    """??????? try_begin_group_owned_gate("pallas_image", ...)?"""
    return await try_begin_group_owned_gate("pallas_image", group_id, bot_id, gate_sec=gate_sec)


async def claim_group_message_event(
    plugin: str,
    group_event: GroupMessageEvent,
    bot_id: int,
    *,
    use_plaintext: bool = True,
) -> bool:
    """? Bot ??????????????????? False?"""
    return await try_claim_cross_bot_message(
        plugin,
        group_event.group_id,
        group_event.user_id,
        group_event.get_plaintext(),
        group_event.time,
        bot_id,
        use_plaintext=use_plaintext,
    )


async def claim_group_handler(
    plugin: str,
    event: MessageEvent,
    bot_id: int,
    *,
    use_plaintext: bool = True,
) -> bool:
    """?????? True????? claim_group_message_event?"""
    if not isinstance(event, GroupMessageEvent):
        return True
    return await claim_group_message_event(plugin, event, bot_id, use_plaintext=use_plaintext)
