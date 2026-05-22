"""跨 worker 代指定牛牛执行 OneBot 动作（发群消息、改群名片等）。"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed

from src.common.paths import plugin_data_dir
from src.common.shard.registry.config import is_sharding_active

_PLUGIN = "pallas_shard"
_POLL_SEC = 0.08
_STALE_SEC = 180.0
_DEFAULT_TIMEOUT = 18.0
_inflight: set[str] = set()


def _coord_dir():
    from pathlib import Path

    root = Path(plugin_data_dir(_PLUGIN, create=True)) / "coord" / "bot_action"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _request_path(request_id: str):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in request_id)
    return _coord_dir() / f"{safe}.json"


def _session_lock_path(path) -> Any:
    return path.with_suffix(path.suffix + ".lock")


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


def _read(path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_atomic(path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _mutate(path, fn) -> dict[str, Any] | None:
    lk = _session_lock_path(path)
    fd = _acquire_lock(lk)
    if fd is None:
        return _read(path)
    try:
        data = _read(path) or {}
        fn(data)
        _write_atomic(path, data)
        return data
    finally:
        _release_lock(fd, lk)


def _publish_request(
    *,
    action: str,
    bot_qq: int,
    payload: dict[str, Any],
    timeout_sec: float,
) -> str:
    request_id = uuid.uuid4().hex
    path = _request_path(request_id)
    now = time.time()

    def init(data: dict[str, Any]) -> None:
        data.clear()
        data.update({
            "request_id": request_id,
            "action": action,
            "bot_qq": int(bot_qq),
            "payload": payload,
            "deadline": now + timeout_sec,
            "created_at": now,
            "done": False,
            "ok": None,
            "result": None,
        })

    _mutate(path, init)
    return request_id


def _finish_request(path, *, ok: bool, result: Any = None) -> None:
    def finish(data: dict[str, Any]) -> None:
        if data.get("done"):
            return
        data["done"] = True
        data["ok"] = ok
        data["result"] = result

    _mutate(path, finish)


async def _wait_request(request_id: str, *, deadline: float) -> tuple[bool, Any]:
    path = _request_path(request_id)
    while time.time() < deadline:
        data = await asyncio.to_thread(_read, path)
        if data and data.get("done"):
            return bool(data.get("ok")), data.get("result")
        await asyncio.sleep(_POLL_SEC)
    return False, None


def _message_from_payload(payload: dict[str, Any]) -> Message | str:
    cq = payload.get("message_cq")
    if isinstance(cq, str) and cq.strip():
        msg: Message | str = Message(cq)
    else:
        text = str(payload.get("message_text") or "")
        msg = text or Message()
    image_b64 = payload.get("image_b64")
    if isinstance(image_b64, str) and image_b64:
        try:
            raw = base64.b64decode(image_b64.encode("ascii"))
            if isinstance(msg, Message):
                msg = msg + Message(MessageSegment.image(raw))
            else:
                msg = Message(msg) + Message(MessageSegment.image(raw))
        except Exception:
            pass
    return msg


async def _execute_local(action: str, bot_qq: int, payload: dict[str, Any]) -> tuple[bool, Any]:
    from nonebot import get_bots

    inst = get_bots().get(str(int(bot_qq)))
    if inst is None:
        return False, None
    gid = payload.get("group_id")
    try:
        if action == "send_group_msg":
            if gid is None:
                return False, None
            msg = _message_from_payload(payload)
            await inst.send_group_msg(group_id=int(gid), message=msg)
            return True, None
        if action == "send_private_msg":
            uid = payload.get("user_id")
            if uid is None:
                return False, None
            msg = _message_from_payload(payload)
            await inst.send_private_msg(user_id=int(uid), message=msg)
            return True, None
        if action == "set_group_card":
            uid = payload.get("user_id")
            card = str(payload.get("card") or "")
            if gid is None or uid is None:
                return False, None
            await inst.call_api(
                "set_group_card",
                group_id=int(gid),
                user_id=int(uid),
                card=card[:60],
            )
            return True, None
        if action == "get_group_member_info":
            uid = payload.get("user_id")
            if gid is None or uid is None:
                return False, None
            info = await inst.call_api(
                "get_group_member_info",
                group_id=int(gid),
                user_id=int(uid),
                no_cache=bool(payload.get("no_cache", True)),
            )
            card = str(info.get("card") or info.get("nickname") or "").strip()
            return True, card
    except ActionFailed as err:
        logger.debug(f"bot_action local {action} qq={bot_qq}: {err}")
        return False, None
    except Exception as err:
        logger.debug(f"bot_action local {action} qq={bot_qq}: {err}")
        return False, None
    return False, None


async def invoke_bot_action(
    action: str,
    bot_qq: int,
    payload: dict[str, Any],
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT,
) -> tuple[bool, Any]:
    """本进程有连接则本地执行；分片且牛在别片则写 coord 请求并等待。"""
    from src.common.shard.presence import bot_has_local_connection

    qq = int(bot_qq)
    if bot_has_local_connection(qq):
        return await _execute_local(action, qq, payload)
    if not is_sharding_active():
        return False, None

    request_id = await asyncio.to_thread(
        _publish_request,
        action=action,
        bot_qq=qq,
        payload=payload,
        timeout_sec=timeout_sec,
    )
    deadline = time.time() + timeout_sec + 2.0
    return await _wait_request(request_id, deadline=deadline)


async def send_private_msg_as_bot(
    bot_qq: int,
    user_id: int,
    message: Message | str,
    *,
    image_bytes: bytes | None = None,
    timeout_sec: float = _DEFAULT_TIMEOUT,
) -> bool:
    payload: dict[str, Any] = {
        "user_id": int(user_id),
        "message_cq": str(message) if isinstance(message, Message) else "",
        "message_text": str(message) if not isinstance(message, Message) else "",
    }
    if image_bytes:
        payload["image_b64"] = base64.b64encode(image_bytes).decode("ascii")
    ok, _ = await invoke_bot_action(
        "send_private_msg",
        bot_qq,
        payload,
        timeout_sec=timeout_sec,
    )
    return ok


async def send_group_message_as_bot(
    bot_qq: int,
    group_id: int,
    message: Message | str,
    *,
    image_bytes: bytes | None = None,
    timeout_sec: float = _DEFAULT_TIMEOUT,
) -> bool:
    payload: dict[str, Any] = {
        "group_id": int(group_id),
        "message_cq": str(message) if isinstance(message, Message) else "",
        "message_text": str(message) if not isinstance(message, Message) else "",
    }
    if image_bytes:
        payload["image_b64"] = base64.b64encode(image_bytes).decode("ascii")
    ok, _ = await invoke_bot_action(
        "send_group_msg",
        bot_qq,
        payload,
        timeout_sec=timeout_sec,
    )
    return ok


async def set_group_card_as_bot(
    bot_qq: int,
    group_id: int,
    user_id: int,
    card: str,
    *,
    timeout_sec: float = 12.0,
) -> bool:
    ok, _ = await invoke_bot_action(
        "set_group_card",
        bot_qq,
        {"group_id": int(group_id), "user_id": int(user_id), "card": card},
        timeout_sec=timeout_sec,
    )
    return ok


async def get_member_card_as_bot(
    bot_qq: int,
    group_id: int,
    user_id: int,
    *,
    timeout_sec: float = 12.0,
) -> str:
    ok, result = await invoke_bot_action(
        "get_group_member_info",
        bot_qq,
        {"group_id": int(group_id), "user_id": int(user_id), "no_cache": True},
        timeout_sec=timeout_sec,
    )
    return str(result or "") if ok else ""


async def _run_pending_request(path, local_ids: frozenset[str]) -> None:
    data = await asyncio.to_thread(_read, path)
    if not data or data.get("done"):
        return
    if time.time() > float(data.get("deadline") or 0) + 1.0:
        return
    bot_key = str(int(data.get("bot_qq") or 0))
    if bot_key not in local_ids:
        return
    req_id = str(data.get("request_id") or path.stem)
    if req_id in _inflight:
        return
    _inflight.add(req_id)

    async def job() -> None:
        try:
            action = str(data.get("action") or "")
            ok, result = await _execute_local(action, int(data.get("bot_qq") or 0), data.get("payload") or {})
            await asyncio.to_thread(_finish_request, path, ok=ok, result=result)
        finally:
            _inflight.discard(req_id)

    asyncio.create_task(job())


async def poll_bot_action_pending(local_ids: frozenset[str]) -> None:
    if not local_ids:
        return
    coord = _coord_dir()
    for path in coord.glob("*.json"):
        if ".lock" in path.name:
            continue
        await _run_pending_request(path, local_ids)
    now = time.time()
    for path in coord.glob("*.json"):
        row = await asyncio.to_thread(_read, path)
        if not row or not row.get("done"):
            continue
        created = float(row.get("created_at") or 0)
        if now - created > _STALE_SEC:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


async def prune_stale_bot_action_files() -> None:
    now = time.time()
    for path in _coord_dir().glob("*.json"):
        row = await asyncio.to_thread(_read, path)
        if row is None:
            continue
        if now > float(row.get("deadline") or 0) + _STALE_SEC:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
