"""分片 worker：跨片同步做梦群注册与梦话漂流投递。"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from collections import deque
from typing import Any

from nonebot import logger

from src.platform.shard import context as shard_ctx
from src.platform.shard.coord.coord_redis_store import coord_key, mutate_json_sync, read_json_sync
from src.platform.shard.registry.config import get_shard_registry_settings

_REDIS_CHANNEL = "pallas:dream_drift"
_seen_event_ids: deque[str] = deque(maxlen=8000)
_seen_set: set[str] = set()
_redis_listener_started = False
_missing_redis_warned = False


def dream_active_key(bot_id: int) -> str:
    return coord_key("dream_active", bot_id)


def drift_payload_to_dict(payload) -> dict[str, Any]:
    from src.plugins.dream.payload import DriftPayload

    if not isinstance(payload, DriftPayload):
        raise TypeError("payload must be DriftPayload")
    out: dict[str, Any] = {"nickname": str(payload.nickname or "")}
    if payload.text:
        out["text"] = str(payload.text)
    if payload.image_bytes:
        out["image_b64"] = base64.b64encode(payload.image_bytes).decode("ascii")
    return out


def drift_payload_from_dict(data: dict[str, Any]):
    from src.plugins.dream.payload import DriftPayload

    nick = str(data.get("nickname") or "").strip() or "某位博士"
    text = data.get("text")
    text_out = str(text) if isinstance(text, str) and text else None
    image_b64 = data.get("image_b64")
    image_bytes = None
    if isinstance(image_b64, str) and image_b64:
        try:
            image_bytes = base64.b64decode(image_b64.encode("ascii"))
        except Exception:
            image_bytes = None
    return DriftPayload(nickname=nick, text=text_out, image_bytes=image_bytes)


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


def _active_ttl_sec(data: dict[str, Any]) -> int:
    groups = data.get("groups")
    if not isinstance(groups, dict) or not groups:
        return 60
    now = time.time()
    future = [max(0.0, float(v) - now) for v in groups.values()]
    if not future:
        return 60
    return max(60, int(max(future)) + 120)


def _prune_active_groups(groups: dict[str, Any]) -> None:
    now = time.time()
    for gid in list(groups.keys()):
        try:
            until = float(groups[gid])
        except (TypeError, ValueError):
            groups.pop(gid, None)
            continue
        if until <= now:
            groups.pop(gid, None)


def register_dream_active_sync(bot_id: int, group_id: int, until_ts: float) -> bool:
    key = dream_active_key(bot_id)

    def mutator(data: dict[str, Any]) -> None:
        groups = data.setdefault("groups", {})
        if not isinstance(groups, dict):
            data["groups"] = groups = {}
        groups[str(int(group_id))] = float(until_ts)
        _prune_active_groups(groups)

    result = mutate_json_sync(key, mutator, ttl_sec_fn=_active_ttl_sec, create_if_missing=True)
    return result is not None


def unregister_dream_active_sync(bot_id: int, group_id: int) -> bool:
    key = dream_active_key(bot_id)

    def mutator(data: dict[str, Any]) -> None:
        groups = data.get("groups")
        if isinstance(groups, dict):
            groups.pop(str(int(group_id)), None)
            _prune_active_groups(groups)

    existing = read_json_sync(key)
    if existing is None:
        return False
    result = mutate_json_sync(key, mutator, ttl_sec_fn=_active_ttl_sec, create_if_missing=False)
    if result is not None and not (result.get("groups") or {}):
        from src.platform.shard.coord.coord_redis_store import delete_key_sync

        delete_key_sync(key)
    return result is not None


def list_peer_dream_groups_sync(bot_id: int, *, exclude_group_id: int) -> list[int]:
    data = read_json_sync(dream_active_key(bot_id)) or {}
    groups = data.get("groups")
    if not isinstance(groups, dict):
        return []
    now = time.time()
    out: list[int] = []
    for gid_str, until in groups.items():
        try:
            gid = int(gid_str)
            until_f = float(until)
        except (TypeError, ValueError):
            continue
        if until_f <= now or gid == int(exclude_group_id):
            continue
        out.append(gid)
    return out


def drift_event_envelope(
    *,
    bot_id: int,
    source_group_id: int,
    target_group_id: int,
    payload,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id or uuid.uuid4().hex,
        "source_shard_id": int(get_shard_registry_settings().shard_id),
        "bot_id": int(bot_id),
        "source_group_id": int(source_group_id),
        "target_group_id": int(target_group_id),
        "payload": drift_payload_to_dict(payload),
    }


def publish_dream_drift_redis_sync(envelope: dict[str, Any]) -> bool:
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
        logger.warning("dream_drift: sharding cross-worker drift requires Redis; local-only fallback")
        _missing_redis_warned = True


def schedule_register_dream_active(bot_id: int, group_id: int, until_ts: float) -> None:
    if not shard_ctx.sharding_active():
        return

    async def job() -> None:
        try:
            await asyncio.to_thread(register_dream_active_sync, bot_id, group_id, until_ts)
        except Exception as err:
            logger.debug(f"dream_drift register active failed bot={bot_id} group={group_id}: {err}")

    asyncio.create_task(job())


def schedule_unregister_dream_active(bot_id: int, group_id: int) -> None:
    if not shard_ctx.sharding_active():
        return

    async def job() -> None:
        try:
            await asyncio.to_thread(unregister_dream_active_sync, bot_id, group_id)
        except Exception as err:
            logger.debug(f"dream_drift unregister active failed bot={bot_id} group={group_id}: {err}")

    asyncio.create_task(job())


def schedule_publish_dream_drift(
    bot_id: int,
    source_group_id: int,
    target_group_id: int,
    payload,
) -> None:
    if not shard_ctx.sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return

    async def job() -> None:
        try:
            envelope = drift_event_envelope(
                bot_id=bot_id,
                source_group_id=source_group_id,
                target_group_id=target_group_id,
                payload=payload,
            )
            ok = await asyncio.to_thread(publish_dream_drift_redis_sync, envelope)
            if not ok:
                from src.platform.coord.redis_settings import coord_redis_enabled

                if not coord_redis_enabled():
                    _warn_missing_redis_once()
        except Exception as err:
            logger.debug(f"dream_drift publish failed bot={bot_id} target={target_group_id}: {err}")

    asyncio.create_task(job())


async def ingest_dream_drift_event(data: dict[str, Any]) -> None:
    event_id = str(data.get("event_id") or "")
    if not event_id or event_id in _seen_set:
        return
    local_shard = int(get_shard_registry_settings().shard_id)
    source = int(data.get("source_shard_id") or -1)
    if source == local_shard:
        _remember_event(event_id)
        return
    try:
        bot_id = int(data["bot_id"])
        target_group_id = int(data["target_group_id"])
    except (KeyError, TypeError, ValueError):
        return
    raw_payload = data.get("payload")
    if not isinstance(raw_payload, dict):
        return
    try:
        payload = drift_payload_from_dict(raw_payload)
    except Exception:
        return
    from src.plugins.dream.runtime import deliver_drift_payload

    delivered = await deliver_drift_payload(bot_id, target_group_id, payload)
    if delivered:
        _remember_event(event_id)


async def dream_drift_redis_listen_loop() -> None:
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    while True:
        if not shard_ctx.sharding_active() or get_shard_registry_settings().role != "worker":
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
            while shard_ctx.sharding_active():
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
                    await ingest_dream_drift_event(data)
        except Exception as err:
            logger.debug(f"dream_drift redis listen: {err}")
            await asyncio.sleep(2.0)
        finally:
            if pubsub is not None:
                try:
                    await asyncio.to_thread(pubsub.close)
                except Exception:
                    pass


def start_dream_drift_redis_listener() -> None:
    global _redis_listener_started
    if _redis_listener_started or not shard_ctx.sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        _warn_missing_redis_once()
        return
    _redis_listener_started = True
    asyncio.create_task(dream_drift_redis_listen_loop(), name="dream_drift_redis_listen")
