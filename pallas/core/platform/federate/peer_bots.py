"""协同池内其它部署牛牛名册。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any

from nonebot import logger

from pallas.core.foundation.command_prefix import matches_command_prefix
from pallas.core.platform.federate.config import (
    federate_ingress_active,
    federate_owner_rotate_sec,
    federate_prefer_local_owner,
    federate_redis_prefix,
)
from pallas.core.platform.federate.redis_settings import get_federate_redis_client
from pallas.core.platform.ingress.plugin_command_plaintext import extract_command_prefixes_from_menu_data
from pallas.core.platform.ingress.route_index import extract_exact_plaintexts_from_menu_data
from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids
from pallas.product.community_stats.store import load_or_create_deployment_id

_PEER_KEY_SEGMENT = "peer_bots"
_PUBLISH_TTL_SEC = max(60, int(os.getenv("PALLAS_FEDERATE_PEER_BOT_TTL_SEC", "180")))
_REFRESH_INTERVAL_SEC = max(15.0, float(os.getenv("PALLAS_FEDERATE_PEER_BOT_REFRESH_SEC", "60")))
_cache_ids: frozenset[int] = frozenset()
_cache_deployment_ids: frozenset[str] = frozenset()
# None = 对端未宣告（旧版），视为全能；frozenset = 明确能力集
_cache_deployment_capabilities: dict[str, frozenset[str] | None] = {}
_cache_updated_mono: float = 0.0
_sync_task: asyncio.Task[None] | None = None


def clear_federate_peer_bot_cache_for_tests() -> None:
    global _cache_deployment_capabilities, _cache_deployment_ids, _cache_ids, _cache_updated_mono, _sync_task
    _cache_ids = frozenset()
    _cache_deployment_ids = frozenset()
    _cache_deployment_capabilities = {}
    _cache_updated_mono = 0.0
    _sync_task = None


def federate_peer_redis_key(deployment_id: str) -> str:
    prefix = federate_redis_prefix()
    return f"{prefix}:{_PEER_KEY_SEGMENT}:{deployment_id.strip().lower()}"


def collect_local_federate_command_capabilities() -> frozenset[str]:
    """本机已加载插件的命令明文能力（exact + prefix），供协同心跳宣告。"""
    try:
        from nonebot import get_loaded_plugins
    except Exception:
        return frozenset()
    caps: set[str] = set()
    try:
        plugins = get_loaded_plugins()
    except Exception:
        return frozenset()
    for plugin in plugins:
        meta = getattr(plugin, "metadata", None)
        extra = getattr(meta, "extra", None) if meta is not None else None
        if not isinstance(extra, dict):
            continue
        menu_data = extra.get("menu_data")
        if not isinstance(menu_data, list):
            continue
        for item in extract_command_prefixes_from_menu_data(menu_data):
            text = str(item).strip()
            if text:
                caps.add(text)
        for item in extract_exact_plaintexts_from_menu_data(menu_data):
            text = str(item).strip()
            if text:
                caps.add(text)
    return frozenset(caps)


def command_capability_covers_plaintext(capabilities: frozenset[str] | None, plain: str) -> bool:
    """``None`` 表示未宣告（旧版全能）；否则看 exact / 前缀是否覆盖明文。"""
    text = (plain or "").strip()
    if not text:
        return False
    if capabilities is None:
        return True
    for cap in capabilities:
        token = str(cap).strip()
        if not token:
            continue
        if text == token or matches_command_prefix(text, token):
            return True
    return False


def get_federate_peer_command_capabilities(deployment_id: str) -> frozenset[str] | None:
    key = deployment_id.strip().lower()
    if key not in _cache_deployment_capabilities:
        return None
    return _cache_deployment_capabilities[key]


def publish_local_federate_peer_bot_ids_sync(bot_ids: set[int] | frozenset[int] | None = None) -> bool:
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is None or not prefix or not deployment_id:
        return False
    ids = sorted(int(qq) for qq in (bot_ids if bot_ids is not None else get_catalog_bot_ids()))
    capabilities = sorted(collect_local_federate_command_capabilities())
    payload_obj: dict[str, Any] = {
        "deployment_id": deployment_id,
        "bot_ids": ids,
        "updated_at": int(time.time()),
    }
    # 插件尚未加载时能力为空：不写字段，避免被当成「零能力」抢走全部命令归属
    if capabilities:
        payload_obj["command_capabilities"] = capabilities

    payload = json.dumps(
        payload_obj,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        return bool(client.set(federate_peer_redis_key(deployment_id), payload, ex=_PUBLISH_TTL_SEC))
    except Exception:
        return False


def _parse_command_capabilities(data: dict[str, Any]) -> frozenset[str] | None:
    if "command_capabilities" not in data:
        return None
    raw = data.get("command_capabilities")
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset()
    caps = {str(item).strip() for item in raw if str(item).strip()}
    return frozenset(caps)


def refresh_federate_peer_bot_ids_sync() -> frozenset[int]:
    global _cache_deployment_capabilities, _cache_deployment_ids, _cache_ids, _cache_updated_mono
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is None or not prefix or not deployment_id:
        _cache_ids = frozenset()
        _cache_deployment_ids = frozenset()
        _cache_deployment_capabilities = {}
        _cache_updated_mono = time.monotonic()
        return _cache_ids
    peer_deployment_ids: set[str] = set()
    peer_ids: set[int] = set()
    peer_capabilities: dict[str, frozenset[str] | None] = {}
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
                peer_capabilities[payload_deployment_id] = _parse_command_capabilities(data)
            for qq in data.get("bot_ids") or []:
                if str(qq).isdigit():
                    peer_ids.add(int(qq))
    except Exception:
        return _cache_ids
    _cache_ids = frozenset(peer_ids)
    _cache_deployment_ids = frozenset(peer_deployment_ids)
    _cache_deployment_capabilities = peer_capabilities
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


def federate_group_owner_ring_index(
    group_id: int,
    ring_size: int,
    *,
    now: float | None = None,
    rotate_sec: int | None = None,
) -> int:
    """协同池内群归属下标；``rotate_sec<=0`` 时仅按群号取模。"""
    if ring_size <= 0:
        return 0
    period = federate_owner_rotate_sec() if rotate_sec is None else max(0, int(rotate_sec))
    if period <= 0:
        return abs(int(group_id)) % ring_size
    epoch = int(time.time() if now is None else now) // period
    digest = hashlib.blake2b(f"{int(group_id)}:{epoch}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % ring_size


def _capable_owner_ring(
    active: list[str],
    *,
    mine: str,
    plain: str | None,
    local_caps: frozenset[str],
) -> list[str]:
    text = (plain or "").strip()
    if not text:
        return active
    capable: list[str] = []
    for dep in active:
        if dep == mine:
            caps: frozenset[str] | None = local_caps
        else:
            caps = _cache_deployment_capabilities.get(dep)
            if dep not in _cache_deployment_capabilities:
                caps = None
        if command_capability_covers_plaintext(caps, text):
            capable.append(dep)
    if capable:
        return capable
    # 无人覆盖该命令：若本机有能力则独担；否则退回全员环（兼容）
    if command_capability_covers_plaintext(local_caps, text):
        return [mine]
    return active


def federate_group_owner_deployment(
    group_id: int,
    *,
    now: float | None = None,
    plain: str | None = None,
) -> str:
    deployment_id = load_or_create_deployment_id().strip().lower()
    if not deployment_id:
        return ""
    active = sorted({deployment_id, *_cache_deployment_ids})
    if not active:
        return deployment_id
    local_caps = collect_local_federate_command_capabilities()
    ring = _capable_owner_ring(active, mine=deployment_id, plain=plain, local_caps=local_caps)
    if federate_prefer_local_owner() and deployment_id in ring:
        return deployment_id
    idx = federate_group_owner_ring_index(int(group_id), len(ring), now=now)
    return ring[idx]


def should_process_federate_group_on_current_deployment(
    group_id: int,
    *,
    plain: str | None = None,
) -> bool:
    if not federate_ingress_active():
        return True
    if not _cache_deployment_ids:
        return True
    deployment_id = load_or_create_deployment_id().strip().lower()
    if not deployment_id:
        return True
    return federate_group_owner_deployment(group_id, plain=plain) == deployment_id


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
