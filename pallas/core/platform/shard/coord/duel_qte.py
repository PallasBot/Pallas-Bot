"""决斗 QTE：Redis 会话与 pub/sub 跨 worker 同步。"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Literal

from nonebot import logger

_POLL_SEC = 0.08
_inflight: set[str] = set()

QteKind = Literal["single", "race"]


def single_qte_session_id(group_id: int, responder: str) -> str:
    return f"s_{group_id}_{responder}"


def race_qte_session_id(group_id: int) -> str:
    return f"r_{group_id}"


def publish_single_qte_request(
    *,
    group_id: int,
    responder: str,
    required_key: str,
    window_sec: int,
    qte_kind: str,
    decoy_keys: list[str] | None,
    deadline: float,
) -> str:
    from pallas.core.platform.shard.coord.duel_qte_redis import read_session_redis_sync, store_session_redis_sync

    session_id = single_qte_session_id(group_id, responder)
    existing = read_session_redis_sync(session_id)
    if (
        isinstance(existing, dict)
        and existing.get("kind") == "single"
        and str(existing.get("responder") or "") == responder
        and not existing.get("done")
    ):
        return session_id

    now = time.time()
    store_session_redis_sync(
        session_id,
        {
            "kind": "single",
            "session_id": session_id,
            "group_id": group_id,
            "responder": responder,
            "required_key": required_key,
            "window_sec": window_sec,
            "qte_kind": qte_kind,
            "decoy_keys": decoy_keys,
            "deadline": deadline,
            "created_at": now,
            "done": False,
            "success": None,
            "winner_uid": None,
        },
    )
    return session_id


def publish_race_qte_request(
    *,
    group_id: int,
    challenger_id: str,
    defender_id: str,
    required_key: str,
    window_sec: int,
    qte_kind: str,
    decoy_keys: list[str] | None,
    deadline: float,
) -> str:
    from pallas.core.platform.shard.coord.duel_qte_redis import read_session_redis_sync, store_session_redis_sync

    session_id = race_qte_session_id(group_id)
    existing = read_session_redis_sync(session_id)
    if isinstance(existing, dict) and existing.get("kind") == "race" and not existing.get("done"):
        return session_id

    now = time.time()
    store_session_redis_sync(
        session_id,
        {
            "kind": "race",
            "session_id": session_id,
            "group_id": group_id,
            "challenger_id": challenger_id,
            "defender_id": defender_id,
            "required_key": required_key,
            "window_sec": window_sec,
            "qte_kind": qte_kind,
            "decoy_keys": decoy_keys,
            "deadline": deadline,
            "created_at": now,
            "done": False,
            "success": None,
            "winner_uid": None,
        },
    )
    return session_id


async def _run_local_single_job(data: dict[str, Any]) -> None:
    from nonebot import get_bots

    from pallas.core.platform.shard.coord.duel_qte_redis import (
        read_session_redis_sync,
        write_single_result_redis_sync,
    )
    from pallas.core.plugin_coord.duel import bot_qte_success_rate, pick_bot_wrong_qte_reply

    group_id = int(data["group_id"])
    responder = str(data["responder"])
    required_key = str(data["required_key"])
    window_sec = int(data["window_sec"])
    qte_kind = str(data.get("qte_kind") or "keyword")
    decoy_keys = data.get("decoy_keys")
    if decoy_keys is not None and not isinstance(decoy_keys, list):
        decoy_keys = None
    deadline = float(data.get("deadline") or 0)
    session_id = str(data.get("session_id") or single_qte_session_id(group_id, responder))

    if time.time() > deadline:
        return
    inst = get_bots().get(responder)
    if inst is None:
        return

    delay = random.uniform(1.2, min(6.0, max(2.0, window_sec - 0.8)))
    success_roll = random.random() < bot_qte_success_rate(qte_kind)
    if not success_roll:
        delay += random.uniform(0.4, 1.8)
    await asyncio.sleep(delay)

    cur = await asyncio.to_thread(read_session_redis_sync, session_id)
    if not cur or cur.get("done") or time.time() > deadline:
        return

    outgoing = required_key if success_roll else pick_bot_wrong_qte_reply(required_key, qte_kind, decoy_keys=decoy_keys)
    ok = bool(success_roll and outgoing == required_key)
    if outgoing:
        try:
            await inst.send_group_msg(group_id=group_id, message=outgoing)
        except Exception as err:
            logger.debug(f"shard duel qte single send failed: {err}")
            ok = False
    await asyncio.to_thread(write_single_result_redis_sync, session_id, success=ok)


async def _run_local_race_job(data: dict[str, Any], responder_id: str) -> None:
    from nonebot import get_bots

    from pallas.core.platform.shard.coord.duel_qte_redis import (
        read_session_redis_sync,
        try_write_race_winner_redis_sync,
    )
    from pallas.core.plugin_coord.duel import bot_qte_success_rate, pick_bot_wrong_qte_reply

    group_id = int(data["group_id"])
    required_key = str(data["required_key"])
    window_sec = int(data["window_sec"])
    qte_kind = str(data.get("qte_kind") or "keyword")
    decoy_keys = data.get("decoy_keys")
    if decoy_keys is not None and not isinstance(decoy_keys, list):
        decoy_keys = None
    deadline = float(data.get("deadline") or 0)
    session_id = str(data.get("session_id") or race_qte_session_id(group_id))

    if time.time() > deadline:
        return
    inst = get_bots().get(responder_id)
    if inst is None:
        return

    delay = random.uniform(1.0, min(5.5, max(1.8, window_sec - 1.0)))
    success_roll = random.random() < bot_qte_success_rate(qte_kind)
    if not success_roll:
        delay += random.uniform(0.3, 1.5)
    await asyncio.sleep(delay)

    cur = await asyncio.to_thread(read_session_redis_sync, session_id)
    if not cur or cur.get("done") or time.time() > deadline:
        return

    outgoing = required_key if success_roll else pick_bot_wrong_qte_reply(required_key, qte_kind, decoy_keys=decoy_keys)
    if outgoing:
        try:
            await inst.send_group_msg(group_id=group_id, message=outgoing)
        except Exception as err:
            logger.debug(f"shard duel qte race send failed: {err}")
            return
    if success_roll and outgoing == required_key:
        await asyncio.to_thread(try_write_race_winner_redis_sync, session_id, responder_id)


async def _process_pending_session(data: dict[str, Any], local_ids: frozenset[str]) -> None:
    if not data or data.get("done"):
        return
    deadline = float(data.get("deadline") or 0)
    if time.time() > deadline + 1.0:
        return

    session_id = str(data.get("session_id") or "")
    kind = data.get("kind")
    if kind == "single":
        responder = str(data.get("responder") or "")
        if responder not in local_ids:
            return
        key = f"{session_id}:single:{responder}"
        if key in _inflight:
            return
        _inflight.add(key)

        async def run() -> None:
            try:
                await _run_local_single_job(data)
            finally:
                _inflight.discard(key)

        asyncio.create_task(run())
        return

    if kind == "race":
        for uid in (str(data.get("challenger_id") or ""), str(data.get("defender_id") or "")):
            if not uid or uid not in local_ids:
                continue
            key = f"{session_id}:race:{uid}"
            if key in _inflight:
                continue
            _inflight.add(key)

            async def run(responder_id: str = uid, inflight_key: str = key) -> None:
                try:
                    await _run_local_race_job(data, responder_id)
                finally:
                    _inflight.discard(inflight_key)

            asyncio.create_task(run())


async def wake_duel_qte_session(session_id: str, local_ids: frozenset[str]) -> None:
    """Redis pub/sub：按 session_id 触发本 worker 上的 QTE 代答。"""
    from pallas.core.platform.shard.coord.duel_qte_redis import read_session_redis_sync

    data = await asyncio.to_thread(read_session_redis_sync, session_id)
    if data:
        await _process_pending_session(data, local_ids)


async def wait_single_qte_coord_result(
    session_id: str,
    fut: asyncio.Future[bool],
    *,
    deadline: float,
) -> None:
    from pallas.core.platform.shard.coord.duel_qte_redis import read_session_redis_sync

    while time.time() < deadline and not fut.done():
        data = await asyncio.to_thread(read_session_redis_sync, session_id)
        if data and data.get("done") and data.get("success") is not None:
            if not fut.done():
                fut.set_result(bool(data.get("success")))
            return
        await asyncio.sleep(_POLL_SEC)


async def wait_race_qte_coord_result(
    session_id: str,
    fut: asyncio.Future[str | None],
    *,
    deadline: float,
) -> None:
    from pallas.core.platform.shard.coord.duel_qte_redis import read_session_redis_sync

    while time.time() < deadline and not fut.done():
        data = await asyncio.to_thread(read_session_redis_sync, session_id)
        if data and data.get("done"):
            winner = data.get("winner_uid")
            if winner is not None and not fut.done():
                fut.set_result(str(winner))
            return
        await asyncio.sleep(_POLL_SEC)


def schedule_cross_shard_single_qte(
    group_id: int,
    responder: str,
    required_key: str,
    fut: asyncio.Future[bool],
    window_sec: int,
    *,
    qte_kind: str = "keyword",
    decoy_keys: list[str] | None = None,
) -> None:
    deadline = time.time() + window_sec
    session_id = publish_single_qte_request(
        group_id=group_id,
        responder=responder,
        required_key=required_key,
        window_sec=window_sec,
        qte_kind=qte_kind,
        decoy_keys=decoy_keys,
        deadline=deadline,
    )

    async def bridge() -> None:
        await wait_single_qte_coord_result(session_id, fut, deadline=deadline + 1.5)

    asyncio.create_task(bridge())


def schedule_cross_shard_race_qte(
    group_id: int,
    challenger_id: str,
    defender_id: str,
    required_key: str,
    fut: asyncio.Future[str | None],
    window_sec: int,
    *,
    qte_kind: str = "keyword",
    decoy_keys: list[str] | None = None,
) -> str:
    """发布抢答会话并返回 session_id。"""
    deadline = time.time() + window_sec
    return publish_race_qte_request(
        group_id=group_id,
        challenger_id=challenger_id,
        defender_id=defender_id,
        required_key=required_key,
        window_sec=window_sec,
        qte_kind=qte_kind,
        decoy_keys=decoy_keys,
        deadline=deadline,
    )


async def bridge_race_qte_coord(session_id: str, fut: asyncio.Future[str | None], *, window_sec: int) -> None:
    deadline = time.time() + window_sec
    await wait_race_qte_coord_result(session_id, fut, deadline=deadline + 1.5)


async def try_claim_race_coord_winner(session_id: str, winner_uid: str) -> bool:
    from pallas.core.platform.shard.coord.duel_qte_redis import try_write_race_winner_redis_sync

    return await asyncio.to_thread(try_write_race_winner_redis_sync, session_id, winner_uid)
