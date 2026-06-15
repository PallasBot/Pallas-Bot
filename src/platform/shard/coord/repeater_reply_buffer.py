"""分片 worker：跨片同步 repeater 牛牛回复缓存。"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from typing import Any

from nonebot import logger

from src.platform.shard.registry.config import get_shard_registry_settings, is_sharding_active

_REDIS_CHANNEL = "pallas:repeater_reply_buffer"
_MAX_BOT_TAIL = 64
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


def reply_record_payload(group_id: int, bot_id: int, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "group_id": int(group_id),
        "bot_id": int(bot_id),
        "time": int(record.get("time") or 0),
        "pre_raw_message": str(record.get("pre_raw_message") or ""),
        "pre_keywords": str(record.get("pre_keywords") or ""),
        "reply": str(record.get("reply") or ""),
        "reply_keywords": str(record.get("reply_keywords") or ""),
    }


def buffer_event_envelope(
    group_id: int,
    bot_id: int,
    record: dict[str, Any],
    *,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id or uuid.uuid4().hex,
        "source_shard_id": int(get_shard_registry_settings().shard_id),
        "record": reply_record_payload(group_id, bot_id, record),
    }


def publish_repeater_reply_buffer_redis_sync(envelope: dict[str, Any]) -> bool:
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
        logger.warning("repeater_reply_buffer: sharding requires Redis; skip publish")
        _missing_redis_warned = True


def publish_repeater_reply_record_sync(group_id: int, bot_id: int, record: dict[str, Any]) -> None:
    if not is_sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return
    envelope = buffer_event_envelope(group_id, bot_id, record)
    if publish_repeater_reply_buffer_redis_sync(envelope):
        return
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        _warn_missing_redis_once()


def schedule_publish_repeater_reply_record(group_id: int, bot_id: int, record: dict[str, Any]) -> None:
    if not is_sharding_active():
        return

    async def job() -> None:
        try:
            await asyncio.to_thread(publish_repeater_reply_record_sync, group_id, bot_id, record)
        except Exception as err:
            logger.debug(f"repeater_reply_buffer publish: {err}")

    asyncio.create_task(job())


def _record_tail_dup(records: list, record: dict[str, Any]) -> bool:
    t = int(record.get("time") or 0)
    reply = str(record.get("reply") or "")
    keywords = str(record.get("reply_keywords") or "")
    for item in records[-8:]:
        if int(item.get("time") or 0) == t and str(item.get("reply") or "") == reply:
            if str(item.get("reply_keywords") or "") == keywords:
                return True
    return False


async def apply_repeater_reply_record(record: dict[str, Any]) -> bool:
    from src.plugins.repeater.model import Chat

    group_id = int(record["group_id"])
    bot_id = int(record["bot_id"])
    entry = {
        "time": int(record.get("time") or 0),
        "pre_raw_message": str(record.get("pre_raw_message") or ""),
        "pre_keywords": str(record.get("pre_keywords") or ""),
        "reply": str(record.get("reply") or ""),
        "reply_keywords": str(record.get("reply_keywords") or ""),
    }
    async with Chat._reply_lock:
        bucket = Chat._reply_dict[group_id][bot_id]
        if _record_tail_dup(bucket, entry):
            return False
        bucket.append(entry)
        if len(bucket) > _MAX_BOT_TAIL:
            del bucket[: len(bucket) - _MAX_BOT_TAIL]
    return True


async def ingest_repeater_reply_buffer_event(data: dict[str, Any]) -> None:
    event_id = str(data.get("event_id") or "")
    if not event_id or event_id in _seen_set:
        return
    local_shard = int(get_shard_registry_settings().shard_id)
    source = int(data.get("source_shard_id") or -1)
    if source == local_shard:
        _remember_event(event_id)
        return
    record = data.get("record")
    if not isinstance(record, dict):
        return
    await apply_repeater_reply_record(record)
    _remember_event(event_id)


async def repeater_reply_buffer_redis_listen_loop() -> None:
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
                    await ingest_repeater_reply_buffer_event(data)
        except Exception as err:
            logger.debug(f"repeater_reply_buffer redis listen: {err}")
            await asyncio.sleep(2.0)
        finally:
            if pubsub is not None:
                try:
                    await asyncio.to_thread(pubsub.close)
                except Exception:
                    pass


def start_repeater_reply_buffer_redis_listener() -> None:
    global _redis_listener_started
    if _redis_listener_started or not is_sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return
    _redis_listener_started = True
    asyncio.create_task(repeater_reply_buffer_redis_listen_loop())
