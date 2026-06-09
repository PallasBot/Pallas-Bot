"""跨 worker「牛牛报数」：各分片登记本群在线牛，汇总后统一随机顺序依次发言。"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime
from typing import Any

from nonebot import logger

from src.platform.multi_bot.dedup import cross_bot_group_message_key
from src.platform.shard.coord.coord_redis_store import (
    coord_key,
    mutate_json_sync,
    read_json_sync,
)
from src.platform.shard.registry.config import get_shard_registry_settings

_BOT_COUNT_TEXTS = frozenset({"牛牛报数", "牛牛出列"})
_COLLECT_SEC = 3.0
_POLL_SEC = 0.08
_STABLE_SEC = 0.45
_POST_COLLECT_GRACE_SEC = 2.5
_SESSION_TTL_SEC = 3600
STAGGER_SEC = 0.35


def is_shard_bot_count_command_plaintext(plain: str) -> bool:
    """牛牛报数 / 牛牛出列：分片协调依赖各 worker 同时进入 handler。"""
    return (plain or "").strip() in _BOT_COUNT_TEXTS


def should_skip_ingress_claim_for_shard_bot_count(plain: str) -> bool:
    """分片 ingress 门控：报数类明文恒 fanout，不受 PALLAS_INGRESS_FANOUT_GREETING 限制。"""
    from src.platform.shard.registry.config import is_sharding_active

    return is_sharding_active() and is_shard_bot_count_command_plaintext(plain)


def is_bot_count_fanout_plaintext(plain: str) -> bool:
    if should_skip_ingress_claim_for_shard_bot_count(plain):
        return True
    text = (plain or "").strip()
    if text not in _BOT_COUNT_TEXTS:
        return False
    from src.platform.shard.ingress_fanout import is_ingress_fanout_plaintext

    return is_ingress_fanout_plaintext(text)


def _session_key(group_id: int, claim_key: int) -> str:
    return coord_key("bot_count", group_id, claim_key)


def _session_path(group_id: int, claim_key: int) -> str:
    return _session_key(group_id, claim_key)


def _write_session_atomic(session_key: str, data: dict[str, Any]) -> None:
    from src.platform.shard.coord.coord_redis_store import setex_json_sync

    setex_json_sync(session_key, data, _session_ttl(data))


def _session_ttl(data: dict[str, Any]) -> int:
    until = float(data.get("collect_until") or 0)
    return max(120, int(until - time.time()) + _SESSION_TTL_SEC)


async def prune_stale_bot_count_files(*, max_age_sec: float = 3600.0) -> int:
    """Redis TTL 自动过期。"""
    return 0


def _read_session(session_key: str) -> dict[str, Any] | None:
    return read_json_sync(session_key)


def _mutate_session(session_key: str, fn) -> dict[str, Any] | None:
    return mutate_json_sync(session_key, fn, ttl_sec_fn=_session_ttl)


def _ensure_session(
    session_key: str,
    *,
    group_id: int,
    user_id: int,
    message_time: int,
    seed: str,
) -> dict[str, Any]:
    now = time.time()

    def init(data: dict[str, Any]) -> None:
        if data.get("group_id"):
            return
        data.update({
            "group_id": group_id,
            "user_id": user_id,
            "message_time": message_time,
            "seed": seed,
            "collect_until": now + _COLLECT_SEC,
            "shards": {},
            "order": None,
            "cancelled": False,
        })

    out = _mutate_session(session_key, init)
    return out or {}


def _register_shard_bots(session_key: str, shard_id: int, bot_ids: list[int]) -> None:
    key = str(shard_id)

    def reg(data: dict[str, Any]) -> None:
        shards = data.setdefault("shards", {})
        merged = {int(x) for x in shards.get(key, []) if str(x).isdigit()}
        merged.update(int(x) for x in bot_ids)
        shards[key] = sorted(merged)
        now = time.time()
        cur = float(data.get("collect_until") or 0)
        data["collect_until"] = max(cur, now + _COLLECT_SEC)

    _mutate_session(session_key, reg)


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


def _registered_shard_keys(data: dict[str, Any]) -> tuple[str, ...]:
    shards = data.get("shards")
    if not isinstance(shards, dict):
        return ()
    return tuple(sorted(str(k) for k in shards.keys()))


def _registration_fingerprint(data: dict[str, Any]) -> tuple[tuple[int, ...], tuple[str, ...]]:
    return (tuple(_all_registered_bots(data)), _registered_shard_keys(data))


def _try_finalize_order(session_key: str, self_bot_id: int) -> dict[str, Any] | None:
    def finalize(data: dict[str, Any]) -> None:
        if data.get("cancelled"):
            return
        if time.time() < float(data.get("collect_until") or 0):
            return
        registered = _all_registered_bots(data)
        if not registered:
            return
        existing = data.get("order")
        if isinstance(existing, list) and existing:
            try:
                order_ids = {int(x) for x in existing}
            except (TypeError, ValueError):
                order_ids = set()
            if order_ids == set(registered):
                return
        order = list(registered)
        seed = str(data.get("seed") or "")
        random.Random(seed).shuffle(order)
        data["order"] = order
        data["finalized_by"] = self_bot_id

    return _mutate_session(session_key, finalize)


async def _wait_collect_until(session_key: str) -> None:
    while True:
        data = await asyncio.to_thread(_read_session, session_key)
        if not data:
            return
        until = float(data.get("collect_until") or 0)
        if time.time() >= until:
            return
        await asyncio.sleep(min(_POLL_SEC, max(0.02, until - time.time())))


def _stable_deadline_from_session(data: dict[str, Any] | None, *, base: float) -> float:
    if not data:
        return base
    until = float(data.get("collect_until") or 0)
    return max(base, until + _POST_COLLECT_GRACE_SEC)


async def _wait_registration_stable(session_key: str, *, deadline: float) -> None:
    """收集截止后，等待各 worker 分片键与登记牛集合同时短暂稳定再 finalize。"""
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


def _order_matches_registration(order: list[int], registered: list[int]) -> bool:
    return set(order) == set(registered)


async def _wait_for_order(session_key: str, *, deadline: float, self_bot_id: int) -> list[int] | None:
    end = deadline
    while time.time() < end:
        data = await asyncio.to_thread(_read_session, session_key)
        end = max(end, _stable_deadline_from_session(data, base=deadline) + 3.0)
        if not data:
            await asyncio.sleep(_POLL_SEC)
            continue
        if data.get("cancelled"):
            return None
        registered = _all_registered_bots(data)
        if registered and time.time() >= float(data.get("collect_until") or 0) and min(registered) == self_bot_id:
            order = data.get("order")
            stale = not isinstance(order, list) or not order
            if not stale:
                try:
                    stale = not _order_matches_registration([int(x) for x in order], registered)
                except (TypeError, ValueError):
                    stale = True
            if stale:
                await asyncio.to_thread(_try_finalize_order, session_key, self_bot_id)
                data = await asyncio.to_thread(_read_session, session_key) or data
                registered = _all_registered_bots(data)
        order = data.get("order")
        if isinstance(order, list) and order:
            try:
                out = [int(x) for x in order]
            except (TypeError, ValueError):
                out = []
            if out and _order_matches_registration(out, registered) and self_bot_id in out:
                return out
        if time.time() >= float(data.get("collect_until") or 0) and not registered:
            break
        await asyncio.sleep(_POLL_SEC)
    data = await asyncio.to_thread(_read_session, session_key)
    if not data or data.get("cancelled"):
        return None
    registered = _all_registered_bots(data)
    order = data.get("order")
    if isinstance(order, list) and order:
        try:
            out = [int(x) for x in order]
        except (TypeError, ValueError):
            return None
        if out and _order_matches_registration(out, registered) and self_bot_id in out:
            return out
    return None


async def update_shard_bot_count_registration(
    *,
    group_id: int,
    user_id: int,
    plaintext: str,
    message_time: int,
    bot_ids: list[int],
) -> None:
    """handler 在慢路径探测本群在线牛后补登记（须与 run_shard_coordinated_bot_count 同 claim_key）。"""
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        plaintext,
        message_time,
        use_plaintext=True,
    )
    session_key = _session_key(group_id, claim_key)
    shard_id = get_shard_registry_settings().shard_id
    await asyncio.to_thread(_register_shard_bots, session_key, shard_id, bot_ids)


async def run_shard_coordinated_bot_count(
    *,
    group_id: int,
    user_id: int,
    plaintext: str,
    message_time: int,
    self_bot_id: int,
    local_bot_ids: list[int] | None = None,
) -> tuple[int, int] | None:
    """
    返回 (1-based 序号, 参与总数)；None 表示不参与（冷却中、未入群、协调失败等）。

    local_bot_ids 可仅含 self_bot_id：handler 应先 create_task 本协程，再探测本群在线牛并
    调用 update_shard_bot_count_registration 补全登记。
    """
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        plaintext,
        message_time,
        use_plaintext=True,
    )
    session_key = _session_key(group_id, claim_key)
    seed = f"{datetime.now().strftime('%Y-%m-%d')}:{group_id}"
    await asyncio.to_thread(
        _ensure_session,
        session_key,
        group_id=group_id,
        user_id=user_id,
        message_time=message_time,
        seed=seed,
    )

    shard_id = get_shard_registry_settings().shard_id
    await asyncio.to_thread(_register_shard_bots, session_key, shard_id, [self_bot_id])
    if local_bot_ids:
        ids = {int(x) for x in local_bot_ids}
        ids.add(self_bot_id)
        await asyncio.to_thread(_register_shard_bots, session_key, shard_id, sorted(ids))

    await _wait_collect_until(session_key)
    data_after_collect = await asyncio.to_thread(_read_session, session_key)
    stable_deadline = _stable_deadline_from_session(data_after_collect, base=time.time() + _POST_COLLECT_GRACE_SEC)
    await _wait_registration_stable(session_key, deadline=stable_deadline)

    registered = await asyncio.to_thread(lambda: _all_registered_bots(_read_session(session_key) or {}))
    if registered and min(registered) == self_bot_id:
        from src.foundation.config import GroupConfig

        config = GroupConfig(group_id=group_id, cooldown=10)
        if not await config.is_cooldown("bot_count"):
            logger.debug("bot_count: group {} skipped (cooldown)", group_id)

            def cancel(data: dict[str, Any]) -> None:
                data["cancelled"] = True

            await asyncio.to_thread(_mutate_session, session_key, cancel)
            return None
        await config.refresh_cooldown("bot_count")

    await asyncio.to_thread(_try_finalize_order, session_key, self_bot_id)

    data0 = await asyncio.to_thread(_read_session, session_key)
    deadline = _stable_deadline_from_session(data0, base=time.time() + 1.0) + 3.0
    order = await _wait_for_order(session_key, deadline=deadline, self_bot_id=self_bot_id)
    if not order or self_bot_id not in order:
        if data0 and not data0.get("cancelled"):
            shards = data0.get("shards") if isinstance(data0.get("shards"), dict) else {}
            logger.warning(
                "bot_count: coord incomplete group={} self={} shards={} order={}",
                group_id,
                self_bot_id,
                list(shards.keys()),
                order,
            )
        return None
    return order.index(self_bot_id) + 1, len(order)
