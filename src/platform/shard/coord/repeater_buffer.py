"""分片 worker：跨片同步 repeater 内存近期群消息。"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from typing import TYPE_CHECKING, Any

from nonebot import logger

from src.platform.shard.registry.config import get_shard_registry_settings, is_sharding_active

if TYPE_CHECKING:
    from src.plugins.repeater.model import ChatData

_REDIS_CHANNEL = "pallas:repeater_buffer"
_MAX_GROUP_TAIL = 256
_seen_event_ids: deque[str] = deque(maxlen=8000)
_seen_set: set[str] = set()
_redis_listener_started = False
_missing_redis_warned = False


def _remember_event(event_id: str) -> None:
    if event_id in _seen_set:
        return
    _seen_event_ids.append(event_id)
    _seen_set.add(event_id)
    while len(_seen_set) > len(_seen_event_ids):
        _seen_set.clear()
        _seen_set.update(_seen_event_ids)
    overflow = len(_seen_event_ids) - _seen_event_ids.maxlen
    if overflow > 0:
        for _ in range(overflow):
            old = _seen_event_ids.popleft()
            _seen_set.discard(old)


def message_payload_from_chat_data(chat_data: ChatData) -> dict[str, Any]:
    from src.plugins.repeater.topic_utils import filtered_recent_topics

    return {
        "group_id": int(chat_data.group_id),
        "user_id": int(chat_data.user_id),
        "bot_id": int(chat_data.bot_id),
        "raw_message": str(chat_data.raw_message),
        "is_plain_text": bool(chat_data.is_plain_text),
        "plain_text": str(chat_data.plain_text),
        "keywords": str(chat_data.keywords),
        "topics": filtered_recent_topics(list(getattr(chat_data, "_keywords_list", []) or [])),
        "time": int(chat_data.time),
    }


def buffer_event_envelope(chat_data: ChatData, *, event_id: str | None = None) -> dict[str, Any]:
    return {
        "event_id": event_id or uuid.uuid4().hex,
        "source_shard_id": int(get_shard_registry_settings().shard_id),
        "msg": message_payload_from_chat_data(chat_data),
    }


def publish_repeater_buffer_redis_sync(envelope: dict[str, Any]) -> bool:
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return False
    client = get_coord_redis_client()
    if client is None:
        return False
    try:
        body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        client.publish(_REDIS_CHANNEL, body)
        return True
    except Exception:
        return False


def _warn_missing_redis_once() -> None:
    global _missing_redis_warned
    if not _missing_redis_warned:
        logger.warning("repeater_buffer: sharding requires Redis; skip publish")
        _missing_redis_warned = True


def publish_repeater_buffer_event_sync(chat_data: ChatData) -> None:
    if not is_sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return
    envelope = buffer_event_envelope(chat_data)
    if publish_repeater_buffer_redis_sync(envelope):
        return
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        _warn_missing_redis_once()


def schedule_publish_repeater_buffer(chat_data: ChatData) -> None:
    if not is_sharding_active():
        return

    async def job() -> None:
        try:
            await asyncio.to_thread(publish_repeater_buffer_event_sync, chat_data)
        except Exception as err:
            logger.debug(f"repeater_buffer publish: {err}")

    asyncio.create_task(job())


def _message_tail_dup(group_msgs: list, msg: dict[str, Any]) -> bool:
    uid = int(msg["user_id"])
    t = int(msg["time"])
    plain = str(msg.get("plain_text") or "")
    for m in group_msgs[-8:]:
        if int(m.user_id) == uid and int(m.time) == t and str(m.plain_text or "") == plain:
            return True
    return False


async def ingest_repeater_buffer_event(data: dict[str, Any]) -> None:
    event_id = str(data.get("event_id") or "")
    if not event_id or event_id in _seen_set:
        return
    local_shard = int(get_shard_registry_settings().shard_id)
    source = int(data.get("source_shard_id") or -1)
    if source == local_shard:
        _remember_event(event_id)
        return
    msg = data.get("msg")
    if not isinstance(msg, dict):
        return
    await apply_repeater_buffer_message(msg)
    _remember_event(event_id)


async def apply_repeater_buffer_message(msg: dict[str, Any]) -> bool:
    from src.foundation.db import Message as MessageModel
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.model import Chat

    group_id = int(msg["group_id"])
    async with MessageStore._message_lock:
        group_msgs = MessageStore._message_dict[group_id]
        if _message_tail_dup(group_msgs, msg):
            return False
        group_msgs.append(
            MessageModel.model_construct(
                group_id=group_id,
                user_id=int(msg["user_id"]),
                bot_id=int(msg["bot_id"]),
                raw_message=str(msg["raw_message"]),
                is_plain_text=bool(msg["is_plain_text"]),
                plain_text=str(msg["plain_text"]),
                keywords=str(msg["keywords"]),
                time=int(msg["time"]),
            )
        )
        if len(group_msgs) > _MAX_GROUP_TAIL:
            del group_msgs[: len(group_msgs) - _MAX_GROUP_TAIL]
    topics = msg.get("topics")
    if isinstance(topics, list):
        await Chat.merge_recent_topics(group_id, [str(item) for item in topics])
    return True


async def repeater_buffer_redis_listen_loop() -> None:
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    while True:
        if not is_sharding_active() or get_shard_registry_settings().role != "worker":
            return
        if not coord_redis_enabled():
            await asyncio.sleep(5.0)
            continue
        client = get_coord_redis_client()
        if client is None:
            await asyncio.sleep(5.0)
            continue
        pubsub = None
        try:
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            await asyncio.to_thread(pubsub.subscribe, _REDIS_CHANNEL)
            while is_sharding_active():
                raw = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if not raw or raw.get("type") != "message":
                    continue
                body = raw.get("data")
                if isinstance(body, bytes):
                    body = body.decode("utf-8")
                if not isinstance(body, str):
                    continue
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    await ingest_repeater_buffer_event(data)
        except Exception as err:
            logger.debug(f"repeater_buffer redis listen: {err}")
            await asyncio.sleep(2.0)
        finally:
            if pubsub is not None:
                try:
                    await asyncio.to_thread(pubsub.close)
                except Exception:
                    pass


def start_repeater_buffer_redis_listener() -> None:
    global _redis_listener_started
    if _redis_listener_started or not is_sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return
    _redis_listener_started = True
    asyncio.create_task(repeater_buffer_redis_listen_loop())
