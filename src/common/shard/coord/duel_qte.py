"""跨 worker 决斗 QTE：主持 worker 写共享会话，应答牛所在 worker 发群并回写结果。"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import Any, Literal

from nonebot import logger

from src.common.paths import plugin_data_dir

_PLUGIN = "pallas_shard"
_POLL_SEC = 0.08
_WATCH_SEC = 0.12
_STALE_SEC = 120.0

QteKind = Literal["single", "race"]


def _coord_dir():
    from pathlib import Path

    root = Path(plugin_data_dir(_PLUGIN, create=True)) / "coord" / "duel_qte"
    root.mkdir(parents=True, exist_ok=True)
    return root


def single_qte_session_id(group_id: int, responder: str) -> str:
    return f"s_{group_id}_{responder}"


def race_qte_session_id(group_id: int) -> str:
    return f"r_{group_id}"


def _session_path(session_id: str):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return _coord_dir() / f"{safe}.json"


def _lock_path(session_path):
    return session_path.with_suffix(session_path.suffix + ".lock")


def _acquire_lock(lock_path, *, timeout: float = 3.0) -> int | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 10.0:
                    lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.02)
    return None


def _release_lock(fd: int | None, lock_path) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_session(path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_session_atomic(path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _mutate_session(path, fn) -> dict[str, Any] | None:
    lock_path = _lock_path(path)
    fd = _acquire_lock(lock_path)
    if fd is None:
        return _read_session(path)
    try:
        data = _read_session(path) or {}
        fn(data)
        _write_session_atomic(path, data)
        return data
    finally:
        _release_lock(fd, lock_path)


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
    session_id = single_qte_session_id(group_id, responder)
    path = _session_path(session_id)
    now = time.time()

    def init(data: dict[str, Any]) -> None:
        if data.get("kind") == "single" and data.get("responder") == responder and not data.get("done"):
            return
        data.clear()
        data.update({
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
        })

    _mutate_session(path, init)
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
    session_id = race_qte_session_id(group_id)
    path = _session_path(session_id)
    now = time.time()

    def init(data: dict[str, Any]) -> None:
        if data.get("kind") == "race" and not data.get("done"):
            return
        data.clear()
        data.update({
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
        })

    _mutate_session(path, init)
    return session_id


def _write_single_result(path, *, success: bool) -> None:
    def finish(data: dict[str, Any]) -> None:
        if data.get("done"):
            return
        data["done"] = True
        data["success"] = success

    _mutate_session(path, finish)


def _try_write_race_winner(path, *, winner_uid: str) -> bool:
    wrote = False

    def finish(data: dict[str, Any]) -> None:
        nonlocal wrote
        if data.get("done") and data.get("winner_uid"):
            return
        data["done"] = True
        data["winner_uid"] = winner_uid
        wrote = True

    _mutate_session(path, finish)
    data = _read_session(path)
    return wrote and data is not None and str(data.get("winner_uid")) == winner_uid


async def _run_local_single_job(data: dict[str, Any]) -> None:
    from nonebot import get_bots

    from src.plugins.duel.duel_qte import bot_qte_success_rate, pick_bot_wrong_qte_reply

    group_id = int(data["group_id"])
    responder = str(data["responder"])
    required_key = str(data["required_key"])
    window_sec = int(data["window_sec"])
    qte_kind = str(data.get("qte_kind") or "keyword")
    decoy_keys = data.get("decoy_keys")
    if decoy_keys is not None and not isinstance(decoy_keys, list):
        decoy_keys = None
    deadline = float(data.get("deadline") or 0)
    path = _session_path(str(data.get("session_id") or single_qte_session_id(group_id, responder)))

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

    cur = await asyncio.to_thread(_read_session, path)
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
    await asyncio.to_thread(_write_single_result, path, success=ok)


async def _run_local_race_job(data: dict[str, Any], responder_id: str) -> None:
    from nonebot import get_bots

    from src.plugins.duel.duel_qte import bot_qte_success_rate, pick_bot_wrong_qte_reply

    group_id = int(data["group_id"])
    required_key = str(data["required_key"])
    window_sec = int(data["window_sec"])
    qte_kind = str(data.get("qte_kind") or "keyword")
    decoy_keys = data.get("decoy_keys")
    if decoy_keys is not None and not isinstance(decoy_keys, list):
        decoy_keys = None
    deadline = float(data.get("deadline") or 0)
    session_id = str(data.get("session_id") or race_qte_session_id(group_id))
    path = _session_path(session_id)

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

    cur = await asyncio.to_thread(_read_session, path)
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
        await asyncio.to_thread(_try_write_race_winner, path, winner_uid=responder_id)


async def _process_pending_file(path, local_ids: frozenset[str]) -> None:
    data = await asyncio.to_thread(_read_session, path)
    if not data or data.get("done"):
        return
    deadline = float(data.get("deadline") or 0)
    if time.time() > deadline + 1.0:
        return

    kind = data.get("kind")
    if kind == "single":
        responder = str(data.get("responder") or "")
        if responder not in local_ids:
            return
        key = f"{path.name}:single:{responder}"
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
            key = f"{path.name}:race:{uid}"
            if key in _inflight:
                continue
            _inflight.add(key)

            async def run(responder_id: str = uid, inflight_key: str = key) -> None:
                try:
                    await _run_local_race_job(data, responder_id)
                finally:
                    _inflight.discard(inflight_key)

            asyncio.create_task(run())


async def poll_duel_qte_pending(local_ids: frozenset[str]) -> None:
    """各 worker 扫描 QTE 共享会话，对本进程已连接牛执行远程应答。"""
    coord = _coord_dir()
    for path in coord.glob("*.json"):
        if ".lock" in path.name:
            continue
        await _process_pending_file(path, local_ids)


async def prune_stale_duel_qte_files() -> None:
    now = time.time()
    for path in _coord_dir().glob("*.json"):
        if ".lock" in path.name:
            continue
        data = await asyncio.to_thread(_read_session, path)
        if not data or not data.get("done"):
            continue
        created = float(data.get("created_at") or 0)
        if now - created > _STALE_SEC:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


_inflight: set[str] = set()


def start_duel_qte_coord_watcher() -> None:
    from src.common.shard.coord.worker_poll import start_shard_coord_worker_watcher

    start_shard_coord_worker_watcher()


async def wait_single_qte_coord_result(
    session_id: str,
    fut: asyncio.Future[bool],
    *,
    deadline: float,
) -> None:
    path = _session_path(session_id)
    while time.time() < deadline and not fut.done():
        data = await asyncio.to_thread(_read_session, path)
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
    path = _session_path(session_id)
    while time.time() < deadline and not fut.done():
        data = await asyncio.to_thread(_read_session, path)
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
    """发布抢答会话并返回 session_id（主持 worker 可轮询 winner）。"""
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
    return await asyncio.to_thread(
        _try_write_race_winner,
        _session_path(session_id),
        winner_uid=winner_uid,
    )
