"""决斗 QTE：Redis 会话存储、pub/sub 唤醒与跨片 greeting 让路。"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from nonebot import logger

from src.platform.shard import context as shard_ctx

_SESSION_CHANNEL = "pallas:duel_qte:session"
_GREETING_CHANNEL = "pallas:duel_qte:greeting"
_SESSION_KEY_PREFIX = "pallas:duel_qte:session:"
_GREETING_KEY_PREFIX = "pallas:duel_qte:greeting_users:"
_SESSION_MAX_TTL = 120

_session_listener_started = False
_greeting_listener_started = False


def session_redis_key(session_id: str) -> str:
    return f"{_SESSION_KEY_PREFIX}{session_id}"


def greeting_users_redis_key(group_id: str) -> str:
    return f"{_GREETING_KEY_PREFIX}{group_id}"


def session_ttl_from_deadline(deadline: float) -> int:
    return max(60, min(_SESSION_MAX_TTL, int(deadline - time.time()) + 30))


def read_session_redis_sync(session_id: str) -> dict[str, Any] | None:
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return None
    client = get_coord_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(session_redis_key(session_id))
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def store_session_redis_sync(session_id: str, data: dict[str, Any]) -> bool:
    """写入 QTE 会话并 pub/sub 唤醒各 worker。"""
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return False
    client = get_coord_redis_client()
    if client is None:
        return False
    deadline = float(data.get("deadline") or time.time() + 60)
    ttl = session_ttl_from_deadline(deadline)
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    wake = json.dumps({"session_id": session_id}, ensure_ascii=False, separators=(",", ":"))
    try:
        pipe = client.pipeline(transaction=True)
        pipe.setex(session_redis_key(session_id), ttl, body)
        pipe.publish(_SESSION_CHANNEL, wake)
        pipe.execute()
        return True
    except Exception:
        return False


def mutate_session_redis_sync(
    session_id: str,
    mutator,
) -> dict[str, Any] | None:
    from redis.exceptions import WatchError

    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return None
    client = get_coord_redis_client()
    if client is None:
        return None
    key = session_redis_key(session_id)
    for _ in range(8):
        try:
            with client.pipeline() as pipe:
                pipe.watch(key)
                raw = client.get(key)
                if raw is None:
                    pipe.unwatch()
                    return None
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    return None
                mutator(data)
                ttl = session_ttl_from_deadline(float(data.get("deadline") or time.time() + 60))
                encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                pipe.multi()
                pipe.setex(key, ttl, encoded)
                pipe.execute()
                return data
        except WatchError:
            continue
        except Exception:
            return None
    return None


def write_single_result_redis_sync(session_id: str, *, success: bool) -> None:
    def finish(data: dict[str, Any]) -> None:
        if data.get("done"):
            return
        data["done"] = True
        data["success"] = success

    mutate_session_redis_sync(session_id, finish)


def try_write_race_winner_redis_sync(session_id: str, winner_uid: str) -> bool:
    wrote = False

    def finish(data: dict[str, Any]) -> None:
        nonlocal wrote
        if data.get("done") and data.get("winner_uid"):
            return
        data["done"] = True
        data["winner_uid"] = winner_uid
        wrote = True

    result = mutate_session_redis_sync(session_id, finish)
    return wrote and result is not None and str(result.get("winner_uid")) == winner_uid


def publish_duel_qte_greeting_redis_sync(
    group_id: str,
    users: frozenset[str],
    *,
    deadline: float,
) -> bool:
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return False
    client = get_coord_redis_client()
    if client is None:
        return False
    ttl = max(1, int(deadline - time.time()) + 2)
    key = greeting_users_redis_key(group_id)
    envelope = {
        "gid": group_id,
        "users": sorted(users),
        "deadline": deadline,
    }
    try:
        pipe = client.pipeline(transaction=True)
        pipe.delete(key)
        if users:
            pipe.sadd(key, *users)
            pipe.expire(key, ttl)
        body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        pipe.publish(_GREETING_CHANNEL, body)
        pipe.execute()
        return True
    except Exception:
        return False


def clear_duel_qte_greeting_redis_sync(group_id: str) -> bool:
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return False
    client = get_coord_redis_client()
    if client is None:
        return False
    envelope = {"gid": group_id, "users": None, "deadline": 0.0}
    try:
        body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        client.delete(greeting_users_redis_key(group_id))
        client.publish(_GREETING_CHANNEL, body)
        return True
    except Exception:
        return False


def greeting_user_blocked_redis_sync(group_id: str, user_id: str) -> bool:
    """pub/sub 镜像未命中时的兜底。"""
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return False
    client = get_coord_redis_client()
    if client is None:
        return False
    try:
        return bool(client.sismember(greeting_users_redis_key(group_id), user_id))
    except Exception:
        return False


def apply_greeting_envelope(envelope: dict[str, Any]) -> None:
    from src.plugins.duel.duel_qte import apply_cluster_qte_greeting

    gid = str(envelope.get("gid") or "")
    if not gid:
        return
    raw_users = envelope.get("users")
    deadline = float(envelope.get("deadline") or 0)
    if raw_users is None:
        apply_cluster_qte_greeting(gid, None, 0.0)
        return
    if not isinstance(raw_users, list):
        return
    users = frozenset(str(u) for u in raw_users if str(u))
    if not users:
        apply_cluster_qte_greeting(gid, None, 0.0)
        return
    apply_cluster_qte_greeting(gid, users, deadline)


async def duel_qte_session_redis_listen_loop() -> None:
    from nonebot import get_bots

    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled
    from src.platform.shard.coord.duel_qte import wake_duel_qte_session

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
            pubsub.subscribe(_SESSION_CHANNEL)
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
                session_id = str(envelope.get("session_id") or "")
                if not session_id:
                    continue
                local_ids = frozenset(get_bots().keys())
                if not local_ids:
                    continue
                try:
                    await wake_duel_qte_session(session_id, local_ids)
                except Exception as err:
                    logger.debug(f"duel_qte session wake: {err}")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.debug(f"duel_qte session redis listen: {err}")
            await asyncio.sleep(1.0)
        finally:
            if pubsub is not None:
                try:
                    pubsub.unsubscribe(_SESSION_CHANNEL)
                    pubsub.close()
                except Exception:
                    pass


async def duel_qte_greeting_redis_listen_loop() -> None:
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

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
            pubsub.subscribe(_GREETING_CHANNEL)
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
                if isinstance(envelope, dict):
                    apply_greeting_envelope(envelope)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.debug(f"duel_qte greeting redis listen: {err}")
            await asyncio.sleep(1.0)
        finally:
            if pubsub is not None:
                try:
                    pubsub.unsubscribe(_GREETING_CHANNEL)
                    pubsub.close()
                except Exception:
                    pass


def start_duel_qte_redis_listeners() -> None:
    global _session_listener_started, _greeting_listener_started
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not shard_ctx.sharding_active() or not coord_redis_enabled():
        return
    if not _session_listener_started:
        _session_listener_started = True
        asyncio.create_task(duel_qte_session_redis_listen_loop())
    if not _greeting_listener_started:
        _greeting_listener_started = True
        asyncio.create_task(duel_qte_greeting_redis_listen_loop())
