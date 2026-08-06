"""跨 worker「牛牛报数」：各分片登记本群在线牛，汇总后统一随机顺序依次发言。"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime
from typing import Any

from nonebot import logger

from pallas.core.platform.ingress.policy_registry import normalize_ingress_trailing_punct
from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key
from pallas.core.platform.shard.coord.coord_redis_store import (
    coord_key,
    mutate_json_sync,
    read_json_sync,
)
from pallas.core.platform.shard.registry.config import get_shard_registry_settings

_BOT_COUNT_TEXTS = frozenset({"牛牛报数", "牛牛出列"})
_COLLECT_SEC = 3.0
_POLL_SEC = 0.08
_STABLE_SEC = 0.45
_POST_COLLECT_GRACE_SEC = 2.5
_SESSION_TTL_SEC = 3600
STAGGER_SEC = 0.35


def normalize_bot_count_command_plaintext(plain: str) -> str:
    """去掉首尾空白与尾部常见标点，便于 fanout / 协调与 on_command 判定一致。"""
    return normalize_ingress_trailing_punct(plain)


def bot_count_coord_plaintext(plain: str) -> str:
    """协调 claim_key 用：报数命令归一化，其它明文保持 strip 后原样。"""
    normalized = normalize_bot_count_command_plaintext(plain)
    if normalized in _BOT_COUNT_TEXTS:
        return normalized
    return (plain or "").strip()


def is_shard_bot_count_command_plaintext(plain: str) -> bool:
    """牛牛报数 / 牛牛出列：分片协调依赖各 worker 同时进入 handler。"""
    return normalize_bot_count_command_plaintext(plain) in _BOT_COUNT_TEXTS


def _session_key(group_id: int, claim_key: int) -> str:
    return coord_key("bot_count", group_id, claim_key)


def _session_path(group_id: int, claim_key: int) -> str:
    return _session_key(group_id, claim_key)


def _write_session_atomic(session_key: str, data: dict[str, Any]) -> None:
    from pallas.core.platform.shard.coord.coord_redis_store import setex_json_sync

    setex_json_sync(session_key, data, _session_ttl(data))


def _session_ttl(data: dict[str, Any]) -> int:
    until = float(data.get("collect_until") or 0)
    return max(120, int(until - time.time()) + _SESSION_TTL_SEC)


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
            return
        order = list(registered)
        seed = str(data.get("seed") or "")
        random.Random(seed).shuffle(order)
        data["order"] = order
        data["report_until"] = time.time() + (len(order) - 1) * STAGGER_SEC + 0.8
        data["finalized_by"] = self_bot_id

    return _mutate_session(session_key, finalize)


def _mark_bot_count_reported_and_claim_completion(
    session_key: str,
    bot_id: int,
    *,
    allow_timeout: bool = True,
) -> bool:
    claimed = False

    def mark_reported(data: dict[str, Any]) -> None:
        nonlocal claimed
        order = data.get("order")
        if not isinstance(order, list) or not order:
            return
        try:
            order_ids = {int(x) for x in order}
        except (TypeError, ValueError):
            return
        if bot_id not in order_ids:
            return
        reported = {int(x) for x in data.get("reported", [])}
        reported.add(bot_id)
        data["reported"] = sorted(reported)
        if data.get("completion_claimed_by") is not None:
            return
        report_until = float(data.get("report_until") or 0)
        if order_ids <= reported or (allow_timeout and time.time() >= report_until):
            data["completion_claimed_by"] = bot_id
            claimed = True

    _mutate_session(session_key, mark_reported)
    return claimed


async def mark_shard_bot_count_reported_and_claim_completion(
    *,
    group_id: int,
    user_id: int,
    plaintext: str,
    message_time: int,
    bot_id: int,
    allow_timeout: bool = True,
) -> bool:
    """登记成功报数，并由首个完成者负责发送收尾提示。"""
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        bot_count_coord_plaintext(plaintext),
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    session_key = _session_key(group_id, claim_key)
    return await asyncio.to_thread(
        _mark_bot_count_reported_and_claim_completion,
        session_key,
        bot_id,
        allow_timeout=allow_timeout,
    )


async def get_shard_bot_count_order(
    *,
    group_id: int,
    user_id: int,
    plaintext: str,
    message_time: int,
) -> list[int] | None:
    """读取已完成协调的报数顺序，供本机代理逐号发送。"""
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        bot_count_coord_plaintext(plaintext),
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    data = await asyncio.to_thread(_read_session, _session_key(group_id, claim_key))
    if not data or data.get("cancelled"):
        return None
    order = data.get("order")
    if not isinstance(order, list) or not order:
        return None
    try:
        return [int(bot_id) for bot_id in order]
    except (TypeError, ValueError):
        return None


async def wait_shard_bot_count_turn(
    *,
    group_id: int,
    user_id: int,
    plaintext: str,
    message_time: int,
    bot_id: int,
) -> bool:
    """等待报数顺序中的前序账号确认，超时后让调用端降级继续。"""
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        bot_count_coord_plaintext(plaintext),
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    session_key = _session_key(group_id, claim_key)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        data = await asyncio.to_thread(_read_session, session_key)
        if not data or data.get("cancelled"):
            return False
        order = data.get("order")
        if not isinstance(order, list):
            return False
        try:
            order_ids = [int(item) for item in order]
            index = order_ids.index(int(bot_id))
            reported = {int(item) for item in data.get("reported", [])}
        except (TypeError, ValueError):
            return False
        if set(order_ids[:index]) <= reported:
            return True
        await asyncio.sleep(_POLL_SEC)
    return False


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
            if not isinstance(order, list) or not order:
                await asyncio.to_thread(_try_finalize_order, session_key, self_bot_id)
                data = await asyncio.to_thread(_read_session, session_key) or data
        order = data.get("order")
        if isinstance(order, list) and order:
            try:
                out = [int(x) for x in order]
            except (TypeError, ValueError):
                out = []
            if self_bot_id in out:
                return out
        if time.time() >= float(data.get("collect_until") or 0) and not registered:
            break
        await asyncio.sleep(_POLL_SEC)
    data = await asyncio.to_thread(_read_session, session_key)
    if not data or data.get("cancelled"):
        return None
    order = data.get("order")
    if isinstance(order, list) and order:
        try:
            out = [int(x) for x in order]
        except (TypeError, ValueError):
            return None
        if self_bot_id in out:
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
    """handler 在慢路径探测本群在线牛后补登记。"""
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        bot_count_coord_plaintext(plaintext),
        message_time,
        use_plaintext=True,
        include_message_time=True,
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
    返回 (1-based 序号, 参与总数)；None 表示不参与。

    local_bot_ids 可仅含 self_bot_id：handler 应先 create_task 本协程，再探测本群在线牛并
    调用 update_shard_bot_count_registration 补全登记。
    """
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        bot_count_coord_plaintext(plaintext),
        message_time,
        use_plaintext=True,
        include_message_time=True,
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
        from pallas.core.foundation.config import GroupConfig

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
