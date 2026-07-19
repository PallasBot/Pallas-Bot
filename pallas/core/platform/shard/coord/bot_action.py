"""跨 worker 代指定牛牛执行 OneBot 动作。"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed

from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.coord.coord_redis_store import (
    coord_key,
    mutate_json_sync,
    read_json_sync,
    store_json_sync,
)

_POLL_SEC = 0.08
_STALE_SEC = 180.0
_DONE_RETAIN_SEC = 45.0
_OPEN_OVERDUE_GRACE_SEC = 5.0
_DEFAULT_TIMEOUT = 18.0
_WAKE_CHANNEL = "pallas:coord:bot_action:wake"
_inflight: set[str] = set()
_last_stale_open_warn_at = 0.0
_wait_events: dict[str, asyncio.Event] = {}
_listener_started = False


def _request_key(request_id: str) -> str:
    return coord_key("bot_action", request_id)


def _request_ttl(data: dict[str, Any]) -> int:
    deadline = float(data.get("deadline") or time.time() + 60)
    return max(60, min(int(_STALE_SEC), int(deadline - time.time()) + 30))


def _publish_request(
    *,
    action: str,
    bot_qq: int,
    payload: dict[str, Any],
    timeout_sec: float,
) -> str:
    request_id = uuid.uuid4().hex
    now = time.time()
    data = {
        "request_id": request_id,
        "action": action,
        "bot_qq": int(bot_qq),
        "payload": payload,
        "deadline": now + timeout_sec,
        "created_at": now,
        "done": False,
        "ok": None,
        "result": None,
    }
    store_json_sync(
        _request_key(request_id),
        data,
        ttl_sec=_request_ttl(data),
        wake_channel=_WAKE_CHANNEL,
        wake_body={"request_id": request_id},
    )
    return request_id


def _finish_request(request_id: str, *, ok: bool, result: Any = None) -> None:
    def finish(data: dict[str, Any]) -> None:
        if data.get("done"):
            return
        data["done"] = True
        data["ok"] = ok
        data["result"] = result

    mutate_json_sync(_request_key(request_id), finish, ttl_sec_fn=_request_ttl)
    wake_bot_action_request(request_id)


def wake_bot_action_request(request_id: str) -> None:
    event = _wait_events.get(request_id)
    if event is not None:
        event.set()


async def _wait_request(request_id: str, *, deadline: float) -> tuple[bool, Any]:
    event = _wait_events.setdefault(request_id, asyncio.Event())
    try:
        while time.time() < deadline:
            data = await asyncio.to_thread(read_json_sync, _request_key(request_id))
            if data and data.get("done"):
                return bool(data.get("ok")), data.get("result")
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(event.wait(), timeout=min(_POLL_SEC, remaining))
            except TimeoutError:
                pass
            event.clear()
    finally:
        _wait_events.pop(request_id, None)
    return False, None


def _message_from_payload(payload: dict[str, Any]) -> Message | str:
    cq = payload.get("message_cq")
    if isinstance(cq, str) and cq.strip():
        msg: Message | str = Message(cq)
    else:
        text = str(payload.get("message_text") or "")
        msg = text or Message()
    image_b64 = payload.get("image_b64")
    cq_text = str(msg) if isinstance(msg, Message) else str(msg)
    if isinstance(image_b64, str) and image_b64 and "[CQ:image" not in cq_text:
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
        if action == "repeater_fanout_reply":
            from packages.repeater.fanout_reply import run_repeater_reply_for_bot

            async def repeater_job() -> None:
                try:
                    await run_repeater_reply_for_bot(int(bot_qq), payload)
                except Exception as err:
                    logger.warning("repeater_fanout remote bot={} failed: {}", int(bot_qq), err)

            asyncio.create_task(
                repeater_job(),
                name=f"repeater_fanout_reply_{int(bot_qq)}",
            )
            return True, None
        if action == "onebot_call_api":
            api = str(payload.get("api") or "").strip()
            if not api:
                return False, None
            params = payload.get("params")
            if not isinstance(params, dict):
                params = {}
            result = await inst.call_api(api, **params)
            return True, result
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
    from pallas.core.platform.shard.presence import bot_has_cluster_connection, bot_has_local_connection

    qq = int(bot_qq)
    if bot_has_local_connection(qq):
        return await _execute_local(action, qq, payload)
    if not shard_ctx.sharding_active():
        return False, None
    if not bot_has_cluster_connection(qq):
        logger.debug(f"bot_action skip: qq={qq} action={action} not connected in cluster")
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


async def call_onebot_api_as_bot(
    bot_qq: int,
    api: str,
    params: dict[str, Any] | None = None,
    *,
    timeout_sec: float = 45.0,
) -> tuple[bool, Any]:
    """hub 控制台等：本进程无连接时经 coord 在持有该牛的 worker 上 call_api。"""
    payload: dict[str, Any] = {"api": str(api).strip(), "params": dict(params or {})}
    return await invoke_bot_action(
        "onebot_call_api",
        int(bot_qq),
        payload,
        timeout_sec=timeout_sec,
    )


async def _run_pending_request(request_id: str, local_ids: frozenset[str]) -> None:
    data = await asyncio.to_thread(read_json_sync, _request_key(request_id))
    if not data or data.get("done"):
        return
    if time.time() > float(data.get("deadline") or 0) + 1.0:
        return
    bot_key = str(int(data.get("bot_qq") or 0))
    if bot_key not in local_ids:
        return
    req_id = str(data.get("request_id") or request_id)
    if req_id in _inflight:
        return
    _inflight.add(req_id)
    action = str(data.get("action") or "")
    bot_qq = int(data.get("bot_qq") or 0)
    payload = data.get("payload") or {}

    if action == "repeater_fanout_reply":
        try:
            await asyncio.to_thread(_finish_request, req_id, ok=True, result=None)
            await _execute_local(action, bot_qq, payload)
        finally:
            _inflight.discard(req_id)
        return

    async def job() -> None:
        try:
            ok, result = await _execute_local(action, bot_qq, payload)
            await asyncio.to_thread(_finish_request, req_id, ok=ok, result=result)
        finally:
            _inflight.discard(req_id)

    asyncio.create_task(job())


def _maybe_warn_stale_open(row: dict[str, Any], *, now: float) -> None:
    global _last_stale_open_warn_at
    deadline = float(row.get("deadline") or 0)
    if deadline <= 0 or now <= deadline + _OPEN_OVERDUE_GRACE_SEC:
        return
    if now - _last_stale_open_warn_at < 60.0:
        return
    _last_stale_open_warn_at = now
    logger.warning(
        "bot_action 未完成请求已过期 "
        f"request_id={row.get('request_id')} action={row.get('action')} "
        f"bot_qq={row.get('bot_qq')} overdue_s={now - deadline:.0f}"
    )


async def bot_action_redis_listen_loop() -> None:
    from nonebot import get_bots

    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_enabled

    while True:
        if not coord_redis_enabled():
            await asyncio.sleep(2.0)
            continue
        client = get_coord_redis_client()
        if client is None:
            await asyncio.sleep(2.0)
            continue
        pubsub = None
        try:
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(_WAKE_CHANNEL)
            while True:
                msg = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if not msg or msg.get("type") != "message":
                    await asyncio.sleep(0)
                    continue
                data = msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    envelope = json.loads(data)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(envelope, dict):
                    continue
                request_id = str(envelope.get("request_id") or "")
                if not request_id:
                    continue
                wake_bot_action_request(request_id)
                local_ids = frozenset(get_bots().keys())
                if not local_ids:
                    continue
                try:
                    await _run_pending_request(request_id, local_ids)
                except Exception as err:
                    logger.debug(f"bot_action wake: {err}")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.debug(f"bot_action redis listen: {err}")
            await asyncio.sleep(1.0)
        finally:
            if pubsub is not None:
                try:
                    pubsub.unsubscribe(_WAKE_CHANNEL)
                    pubsub.close()
                except Exception:
                    pass


def start_bot_action_redis_listener() -> None:
    global _listener_started
    from pallas.core.platform.coord.redis_settings import coord_redis_enabled

    if _listener_started or not shard_ctx.sharding_active() or not coord_redis_enabled():
        return
    _listener_started = True
    asyncio.create_task(bot_action_redis_listen_loop())
