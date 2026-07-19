"""协同池内其它部署牛牛名册。"""

from __future__ import annotations

import asyncio
import json
import os
import time

from nonebot import logger

from pallas.core.platform.federate.config import federate_ingress_active, federate_redis_prefix
from pallas.core.platform.federate.redis_settings import get_federate_redis_client
from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids
from pallas.product.community_stats.store import load_or_create_deployment_id

_PEER_KEY_SEGMENT = "peer_bots"
_PUBLISH_TTL_SEC = max(60, int(os.getenv("PALLAS_FEDERATE_PEER_BOT_TTL_SEC", "180")))
_REFRESH_INTERVAL_SEC = max(15.0, float(os.getenv("PALLAS_FEDERATE_PEER_BOT_REFRESH_SEC", "60")))
_cache_ids: frozenset[int] = frozenset()
_cache_deployment_ids: frozenset[str] = frozenset()
_cache_updated_mono: float = 0.0
_sync_task: asyncio.Task[None] | None = None


def clear_federate_peer_bot_cache_for_tests() -> None:
    global _cache_deployment_ids, _cache_ids, _cache_updated_mono, _sync_task
    _cache_ids = frozenset()
    _cache_deployment_ids = frozenset()
    _cache_updated_mono = 0.0
    _sync_task = None


def federate_peer_redis_key(deployment_id: str) -> str:
    prefix = federate_redis_prefix()
    return f"{prefix}:{_PEER_KEY_SEGMENT}:{deployment_id.strip().lower()}"


def publish_local_federate_peer_bot_ids_sync(bot_ids: set[int] | frozenset[int] | None = None) -> bool:
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is None or not prefix or not deployment_id:
        return False
    ids = sorted(int(qq) for qq in (bot_ids if bot_ids is not None else get_catalog_bot_ids()))
    payload = json.dumps(
        {
            "deployment_id": deployment_id,
            "bot_ids": ids,
            "updated_at": int(time.time()),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        return bool(client.set(federate_peer_redis_key(deployment_id), payload, ex=_PUBLISH_TTL_SEC))
    except Exception:
        return False


def refresh_federate_peer_bot_ids_sync() -> frozenset[int]:
    global _cache_deployment_ids, _cache_ids, _cache_updated_mono
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is None or not prefix or not deployment_id:
        _cache_ids = frozenset()
        _cache_deployment_ids = frozenset()
        _cache_updated_mono = time.monotonic()
        return _cache_ids
    peer_deployment_ids: set[str] = set()
    peer_ids: set[int] = set()
    pattern = f"{prefix}:{_PEER_KEY_SEGMENT}:*"
    try:
        for raw_key in client.scan_iter(match=pattern, count=100):
            key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
            if key == federate_peer_redis_key(deployment_id):
                continue
            raw = client.get(raw_key)
            if raw is None:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(str(raw))
            if not isinstance(data, dict):
                continue
            payload_deployment_id = str(data.get("deployment_id") or "").strip().lower()
            if not payload_deployment_id:
                payload_deployment_id = key.rsplit(":", 1)[-1].strip().lower()
            if payload_deployment_id and payload_deployment_id != deployment_id:
                peer_deployment_ids.add(payload_deployment_id)
            for qq in data.get("bot_ids") or []:
                if str(qq).isdigit():
                    peer_ids.add(int(qq))
    except Exception:
        return _cache_ids
    _cache_ids = frozenset(peer_ids)
    _cache_deployment_ids = frozenset(peer_deployment_ids)
    _cache_updated_mono = time.monotonic()
    return _cache_ids


def get_federate_peer_bot_ids() -> frozenset[int]:
    return _cache_ids


def get_federate_peer_deployment_ids() -> frozenset[str]:
    return _cache_deployment_ids


def federate_peer_bot_ids_contains(qq: int | str) -> bool:
    try:
        return int(qq) in _cache_ids
    except (TypeError, ValueError):
        return False


def federate_group_owner_deployment(group_id: int) -> str:
    deployment_id = load_or_create_deployment_id().strip().lower()
    if not deployment_id:
        return ""
    active = sorted({deployment_id, *_cache_deployment_ids})
    if not active:
        return deployment_id
    return active[abs(int(group_id)) % len(active)]


def should_process_federate_group_on_current_deployment(group_id: int) -> bool:
    if not federate_ingress_active():
        return True
    if not _cache_deployment_ids:
        return True
    deployment_id = load_or_create_deployment_id().strip().lower()
    if not deployment_id:
        return True
    return federate_group_owner_deployment(group_id) == deployment_id


async def sync_federate_peer_bot_roster() -> None:
    global _cache_ids, _cache_updated_mono
    if not federate_ingress_active():
        _cache_ids = frozenset()
        _cache_updated_mono = time.monotonic()
        return
    await asyncio.to_thread(publish_local_federate_peer_bot_ids_sync)
    peer_ids = await asyncio.to_thread(refresh_federate_peer_bot_ids_sync)
    logger.debug("federate peer bots synced peers={}", len(peer_ids))


async def run_federate_peer_bot_sync_loop() -> None:
    try:
        while True:
            await sync_federate_peer_bot_roster()
            await asyncio.sleep(_REFRESH_INTERVAL_SEC)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.debug("federate peer bots sync loop stopped: {}", e)


def start_federate_peer_bot_sync_loop() -> None:
    global _sync_task
    if _sync_task is not None and not _sync_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _sync_task = loop.create_task(run_federate_peer_bot_sync_loop(), name="federate_peer_bot_sync")
