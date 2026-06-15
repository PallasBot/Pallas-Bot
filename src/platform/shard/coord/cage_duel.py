"""跨 worker「八角笼」：各分片登记本群在线牛，汇总后统一随机配对。"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from nonebot import logger

from src.platform.multi_bot.dedup import cross_bot_group_message_key, normalize_message_time
from src.platform.shard.coord.coord_redis_store import (
    coord_key,
    mutate_json_sync,
    read_json_sync,
)
from src.platform.shard.registry.config import get_shard_registry_settings

_COLLECT_SEC = 3.0
_POLL_SEC = 0.08
_STABLE_SEC = 0.45
_POST_COLLECT_GRACE_SEC = 2.5
_SESSION_TTL_SEC = 3600


def _session_key(group_id: int, claim_key: int) -> str:
    return coord_key("cage_duel", group_id, claim_key)


def _session_path(group_id: int, claim_key: int) -> str:
    return _session_key(group_id, claim_key)


def _write_session_atomic(session_key: str, data: dict[str, Any]) -> None:
    from src.platform.shard.coord.coord_redis_store import setex_json_sync

    setex_json_sync(session_key, data, _session_ttl(data))


def _session_ttl(data: dict[str, Any]) -> int:
    until = float(data.get("collect_until") or 0)
    return max(120, int(until - time.time()) + _SESSION_TTL_SEC)


def _read_session(session_key: str) -> dict[str, Any] | None:
    return read_json_sync(session_key)


def _mutate_session(session_key: str, fn) -> dict[str, Any] | None:
    return mutate_json_sync(session_key, fn, ttl_sec_fn=_session_ttl)


def _all_registered_bots(data: dict[str, Any]) -> list[int]:
    out: set[int] = set()
    shards = data.get("shards")
    if not isinstance(shards, dict):
        return []
    for ids in shards.values():
        if not isinstance(ids, list):
            continue
        for x in ids:
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                continue
    return sorted(out)


def _registration_fingerprint(data: dict[str, Any]) -> tuple[tuple[int, ...], tuple[str, ...]]:
    shards = data.get("shards")
    keys: list[str] = []
    if isinstance(shards, dict):
        keys = sorted(str(k) for k in shards.keys())
    return (tuple(_all_registered_bots(data)), tuple(keys))


def _stable_deadline_from_session(data: dict[str, Any] | None, *, base: float) -> float:
    if not data:
        return base
    until = float(data.get("collect_until") or 0)
    return max(base, until + _POST_COLLECT_GRACE_SEC)


def _ensure_cage_session(
    session_key: str,
    *,
    group_id: int,
    user_id: int,
    message_time: int,
    seed: str,
) -> None:
    """同 claim_key 新消息须开新局；进行中的同一条消息仅延长 collect 窗口。"""
    now = time.time()
    incoming_mt = normalize_message_time(message_time)

    def init(data: dict[str, Any]) -> None:
        gid = data.get("group_id")
        stored_mt = normalize_message_time(data.get("message_time") or 0)
        collect_until = float(data.get("collect_until") or 0)
        completed = bool(data.get("pair")) and now >= collect_until + _POST_COLLECT_GRACE_SEC
        in_flight_same = (
            gid == group_id
            and stored_mt == incoming_mt
            and not completed
            and now < collect_until + _POST_COLLECT_GRACE_SEC + 30.0
        )
        if in_flight_same:
            data["collect_until"] = max(collect_until, now + _COLLECT_SEC)
            return
        data.clear()
        data.update({
            "group_id": group_id,
            "user_id": user_id,
            "message_time": message_time,
            "seed": seed,
            "collect_until": now + _COLLECT_SEC,
            "shards": {},
            "pair": None,
        })

    _mutate_session(session_key, init)


def _register_shard_bots(session_key: str, shard_id: int, bot_ids: list[int]) -> None:
    key = str(shard_id)

    def reg(data: dict[str, Any]) -> None:
        shards = data.setdefault("shards", {})
        merged = {int(x) for x in shards.get(key, []) if str(x).isdigit()}
        merged.update(int(x) for x in bot_ids)
        shards[key] = sorted(merged)
        cur = float(data.get("collect_until") or 0)
        data["collect_until"] = max(cur, time.time() + _COLLECT_SEC)

    _mutate_session(session_key, reg)


def _try_finalize_pair(session_key: str, self_bot_id: int, seed: str) -> None:
    def finalize(data: dict[str, Any]) -> None:
        if data.get("pair"):
            return
        if time.time() < float(data.get("collect_until") or 0):
            return
        registered = _all_registered_bots(data)
        if len(registered) < 2:
            return
        if min(registered) != self_bot_id:
            return
        pair = random.Random(seed).sample(registered, 2)
        data["pair"] = pair
        data["finalized_by"] = self_bot_id

    _mutate_session(session_key, finalize)


async def _wait_collect_until(session_key: str) -> None:
    while True:
        data = await asyncio.to_thread(_read_session, session_key)
        if not data:
            return
        until = float(data.get("collect_until") or 0)
        if time.time() >= until:
            return
        await asyncio.sleep(min(_POLL_SEC, max(0.02, until - time.time())))


async def _wait_registration_stable(session_key: str, *, deadline: float) -> None:
    last_fp: tuple[tuple[int, ...], tuple[str, ...]] | None = None
    stable_since: float | None = None
    end = deadline
    while time.time() < end:
        data = await asyncio.to_thread(_read_session, session_key)
        end = _stable_deadline_from_session(data, base=deadline)
        if not data:
            await asyncio.sleep(_POLL_SEC)
            continue
        if time.time() < float(data.get("collect_until") or 0):
            last_fp = None
            stable_since = None
            await asyncio.sleep(_POLL_SEC)
            continue
        fp = _registration_fingerprint(data)
        if fp[0] and fp == last_fp:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= _STABLE_SEC:
                return
        else:
            last_fp = fp
            stable_since = time.time() if fp[0] else None
        await asyncio.sleep(_POLL_SEC)


async def _wait_for_pair(
    session_key: str,
    *,
    deadline: float,
    self_bot_id: int,
    seed: str,
) -> list[int] | None:
    end = deadline
    while time.time() < end:
        data = await asyncio.to_thread(_read_session, session_key)
        end = max(end, _stable_deadline_from_session(data, base=deadline) + 2.0)
        if not data:
            await asyncio.sleep(_POLL_SEC)
            continue
        registered = _all_registered_bots(data)
        if registered and time.time() >= float(data.get("collect_until") or 0) and min(registered) == self_bot_id:
            if not data.get("pair"):
                await asyncio.to_thread(_try_finalize_pair, session_key, self_bot_id, seed)
                data = await asyncio.to_thread(_read_session, session_key) or data
        pair = data.get("pair")
        if isinstance(pair, list) and len(pair) >= 2:
            try:
                out = [int(x) for x in pair[:2]]
            except (TypeError, ValueError):
                out = []
            if len(out) == 2 and set(out) <= set(registered):
                return out
        await asyncio.sleep(_POLL_SEC)
    data = await asyncio.to_thread(_read_session, session_key)
    if not data:
        return None
    pair = data.get("pair")
    if isinstance(pair, list) and len(pair) >= 2:
        try:
            return [int(pair[0]), int(pair[1])]
        except (TypeError, ValueError):
            return None
    return None


async def update_shard_cage_duel_registration(
    *,
    group_id: int,
    user_id: int,
    message_time: int,
    plaintext: str,
    bot_ids: list[int],
) -> None:
    """handler 在探测本群在线牛后补登记。"""
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        plaintext,
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    session_key = _session_key(group_id, claim_key)
    shard_id = get_shard_registry_settings().shard_id
    await asyncio.to_thread(_register_shard_bots, session_key, shard_id, bot_ids)


async def run_shard_cage_duel_coord(
    *,
    group_id: int,
    user_id: int,
    message_time: int,
    plaintext: str,
    self_bot_id: int,
) -> tuple[int, int] | None:
    """
    各 worker 先登记收到指令的本牛，handler 可再补登记同分片探测到的牛
    汇总后由最小 QQ 牛 finalize 随机配对。
    """
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        plaintext,
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    session_key = _session_key(group_id, claim_key)
    t = normalize_message_time(message_time)
    seed = str(group_id * 1_000_000_007 + user_id * 1_000_003 + t)

    await asyncio.to_thread(
        _ensure_cage_session,
        session_key,
        group_id=group_id,
        user_id=user_id,
        message_time=message_time,
        seed=seed,
    )

    shard_id = get_shard_registry_settings().shard_id
    await asyncio.to_thread(_register_shard_bots, session_key, shard_id, [self_bot_id])

    await _wait_collect_until(session_key)
    data0 = await asyncio.to_thread(_read_session, session_key)
    stable_deadline = _stable_deadline_from_session(data0, base=time.time() + _POST_COLLECT_GRACE_SEC)
    await _wait_registration_stable(session_key, deadline=stable_deadline)

    registered = await asyncio.to_thread(lambda: _all_registered_bots(_read_session(session_key) or {}))
    finalize_bot = min(registered) if registered else 0
    if finalize_bot == self_bot_id:
        await asyncio.to_thread(_try_finalize_pair, session_key, finalize_bot, seed)

    deadline = _stable_deadline_from_session(data0, base=time.time() + 1.0) + 3.0
    pair = await _wait_for_pair(
        session_key,
        deadline=deadline,
        self_bot_id=finalize_bot or self_bot_id,
        seed=seed,
    )
    if not pair:
        data_warn = await asyncio.to_thread(_read_session, session_key) or data0 or {}
        shards = data_warn.get("shards") if isinstance(data_warn.get("shards"), dict) else {}
        registered = _all_registered_bots(data_warn)
        logger.warning(
            "cage_duel: pair incomplete group={} shard={} shards={} registered={} pair={}",
            group_id,
            shard_id,
            list(shards.keys()),
            registered,
            pair,
        )
        return None
    return pair[0], pair[1]
