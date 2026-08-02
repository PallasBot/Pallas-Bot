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
from pallas.core.platform.ingress.route_index import (
    extract_exact_plaintexts_from_menu_data,
    extract_explicit_route_strings,
)
from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids
from pallas.product.community_stats.store import load_or_create_deployment_id

_PEER_KEY_SEGMENT = "peer_bots"
_PRESENT_GROUPS_KEY_SEGMENT = "present_groups"
COMMAND_CAPABILITY_PROTOCOL_VERSION = 1
_PUBLISH_TTL_SEC = max(60, int(os.getenv("PALLAS_FEDERATE_PEER_BOT_TTL_SEC", "180")))
_REFRESH_INTERVAL_SEC = max(15.0, float(os.getenv("PALLAS_FEDERATE_PEER_BOT_REFRESH_SEC", "60")))
_PRESENT_GROUP_WINDOW_SEC = max(_PUBLISH_TTL_SEC, int(os.getenv("PALLAS_FEDERATE_PRESENT_GROUP_WINDOW_SEC", "300")))
_PRESENT_GROUP_PUBLISH_CAP = max(64, int(os.getenv("PALLAS_FEDERATE_PRESENT_GROUP_PUBLISH_CAP", "2000")))
_cache_ids: frozenset[int] = frozenset()
_cache_deployment_ids: frozenset[str] = frozenset()
# None = 对端未宣告（旧版），视为全能；frozenset = 明确能力集
_cache_deployment_capabilities: dict[str, frozenset[str] | None] = {}
# None = 旧端未声明命令能力协议版本。
_cache_deployment_capability_protocols: dict[str, int | None] = {}
# None = 对端未宣告在场群（旧版），视为可能在场；frozenset = 近期在场群
_cache_deployment_present_groups: dict[str, frozenset[int] | None] = {}
_local_present_groups: dict[int, float] = {}
_cache_updated_mono: float = 0.0
_sync_task: asyncio.Task[None] | None = None
_last_incompatible_capability_peers: tuple[str, ...] = ()


def clear_federate_peer_bot_cache_for_tests() -> None:
    global \
        _cache_deployment_capabilities, \
        _cache_deployment_capability_protocols, \
        _cache_deployment_ids, \
        _cache_deployment_present_groups, \
        _cache_ids, \
        _cache_updated_mono, \
        _local_present_groups, \
        _sync_task, \
        _last_incompatible_capability_peers
    _cache_ids = frozenset()
    _cache_deployment_ids = frozenset()
    _cache_deployment_capabilities = {}
    _cache_deployment_capability_protocols = {}
    _cache_deployment_present_groups = {}
    _local_present_groups = {}
    _cache_updated_mono = 0.0
    _sync_task = None
    _last_incompatible_capability_peers = ()


def federate_peer_redis_key(deployment_id: str) -> str:
    prefix = federate_redis_prefix()
    return f"{prefix}:{_PEER_KEY_SEGMENT}:{deployment_id.strip().lower()}"


def federate_present_groups_redis_key(deployment_id: str) -> str:
    prefix = federate_redis_prefix()
    return f"{prefix}:{_PRESENT_GROUPS_KEY_SEGMENT}:{deployment_id.strip().lower()}"


def collect_local_federate_command_capabilities() -> frozenset[str]:
    """本机已加载插件的命令明文能力（exact + prefix），供协同心跳宣告。

    含 ``extra.command_prefixes`` / ``exact_plaintexts``（如唱歌音频映射自定义前缀），
    不仅 menu_data，避免「一歌唱歌」等未进入能力环而被他机夺走。
    """
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
        caps.update(extract_explicit_route_strings(extra.get("command_prefixes")))
        caps.update(extract_explicit_route_strings(extra.get("exact_plaintexts")))
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
    """显式能力集是否覆盖明文。

    ``None`` 表示未宣告（旧版）；是否当作全能由 ``_capable_owner_ring`` 决定，
    本函数对 ``None`` 仍返回 True 以保持调用方语义。
    """
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


def get_federate_peer_command_capability_protocol(deployment_id: str) -> int | None:
    return _cache_deployment_capability_protocols.get(deployment_id.strip().lower())


def get_incompatible_federate_command_capability_peers() -> tuple[str, ...]:
    return tuple(
        sorted(
            deployment_id
            for deployment_id in _cache_deployment_ids
            if _cache_deployment_capability_protocols.get(deployment_id) != COMMAND_CAPABILITY_PROTOCOL_VERSION
        )
    )


def get_federate_peer_present_groups(deployment_id: str) -> frozenset[int] | None:
    key = deployment_id.strip().lower()
    if key not in _cache_deployment_present_groups:
        return None
    return _cache_deployment_present_groups[key]


def touch_federate_present_group(group_id: int) -> None:
    """记录本机某群仍有号在收消息（分片 worker 共用 Redis ZSET）。"""
    try:
        gid = int(group_id)
    except (TypeError, ValueError):
        return
    now = time.time()
    _local_present_groups[gid] = now
    cutoff = now - float(_PRESENT_GROUP_WINDOW_SEC)
    stale = [g for g, ts in _local_present_groups.items() if ts < cutoff]
    for g in stale:
        _local_present_groups.pop(g, None)

    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is None or not prefix or not deployment_id:
        return
    key = federate_present_groups_redis_key(deployment_id)
    try:
        pipe = client.pipeline()
        pipe.zadd(key, {str(gid): now})
        pipe.zremrangebyscore(key, "-inf", cutoff)
        pipe.expire(key, int(_PRESENT_GROUP_WINDOW_SEC) + int(_PUBLISH_TTL_SEC))
        pipe.execute()
    except Exception:
        return


def collect_local_present_group_ids() -> list[int]:
    """心跳用：本机近期在场群（本地 + Redis 合并，有上限）。"""
    now = time.time()
    cutoff = now - float(_PRESENT_GROUP_WINDOW_SEC)
    ids: set[int] = {gid for gid, ts in _local_present_groups.items() if ts >= cutoff}

    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is not None and prefix and deployment_id:
        key = federate_present_groups_redis_key(deployment_id)
        try:
            client.zremrangebyscore(key, "-inf", cutoff)
            raw_members = client.zrangebyscore(key, cutoff, "+inf")
            for item in raw_members or []:
                text = item.decode("utf-8") if isinstance(item, bytes) else str(item)
                if text.isdigit():
                    ids.add(int(text))
        except Exception:
            pass

    ordered = sorted(ids)
    if len(ordered) > _PRESENT_GROUP_PUBLISH_CAP:
        # 保留最近碰过的：按本地时间戳优先，其余按群号截断
        scored = sorted(
            ((_local_present_groups.get(g, 0.0), g) for g in ordered),
            reverse=True,
        )
        ordered = sorted(g for _, g in scored[:_PRESENT_GROUP_PUBLISH_CAP])
    return ordered


def publish_local_federate_peer_bot_ids_sync(bot_ids: set[int] | frozenset[int] | None = None) -> bool:
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is None or not prefix or not deployment_id:
        return False
    ids = sorted(int(qq) for qq in (bot_ids if bot_ids is not None else get_catalog_bot_ids()))
    capabilities = sorted(collect_local_federate_command_capabilities())
    present_groups = collect_local_present_group_ids()
    payload_obj: dict[str, Any] = {
        "deployment_id": deployment_id,
        "bot_ids": ids,
        "updated_at": int(time.time()),
        "present_group_ids": present_groups,
        "command_capability_protocol": COMMAND_CAPABILITY_PROTOCOL_VERSION,
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


def _parse_command_capability_protocol(data: dict[str, Any]) -> int | None:
    raw = data.get("command_capability_protocol")
    if isinstance(raw, bool):
        return None
    try:
        version = int(raw)
    except (TypeError, ValueError):
        return None
    return version if version > 0 else None


def _parse_present_group_ids(data: dict[str, Any]) -> frozenset[int] | None:
    if "present_group_ids" not in data:
        return None
    raw = data.get("present_group_ids")
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset()
    groups: set[int] = set()
    for item in raw:
        if str(item).isdigit():
            groups.add(int(item))
    return frozenset(groups)


def refresh_federate_peer_bot_ids_sync() -> frozenset[int]:
    global \
        _cache_deployment_capabilities, \
        _cache_deployment_capability_protocols, \
        _cache_deployment_ids, \
        _cache_deployment_present_groups, \
        _cache_ids, \
        _cache_updated_mono
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is None or not prefix or not deployment_id:
        _cache_ids = frozenset()
        _cache_deployment_ids = frozenset()
        _cache_deployment_capabilities = {}
        _cache_deployment_present_groups = {}
        _cache_updated_mono = time.monotonic()
        return _cache_ids
    peer_deployment_ids: set[str] = set()
    peer_ids: set[int] = set()
    peer_capabilities: dict[str, frozenset[str] | None] = {}
    peer_protocols: dict[str, int | None] = {}
    peer_present: dict[str, frozenset[int] | None] = {}
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
                peer_protocols[payload_deployment_id] = _parse_command_capability_protocol(data)
                peer_present[payload_deployment_id] = _parse_present_group_ids(data)
            for qq in data.get("bot_ids") or []:
                if str(qq).isdigit():
                    peer_ids.add(int(qq))
    except Exception:
        return _cache_ids
    _cache_ids = frozenset(peer_ids)
    _cache_deployment_ids = frozenset(peer_deployment_ids)
    _cache_deployment_capabilities = peer_capabilities
    _cache_deployment_capability_protocols = peer_protocols
    _cache_deployment_present_groups = peer_present
    _cache_updated_mono = time.monotonic()
    return _cache_ids


def log_incompatible_federate_command_capability_peers() -> None:
    global _last_incompatible_capability_peers
    peers = get_incompatible_federate_command_capability_peers()
    if peers == _last_incompatible_capability_peers:
        return
    _last_incompatible_capability_peers = peers
    if peers:
        logger.warning(
            "[联邦] 对端 {} 未支持命令能力协议 v{}；未知命令仍可能被旧端抢占，请升级并重启这些部署",
            ", ".join(peers),
            COMMAND_CAPABILITY_PROTOCOL_VERSION,
        )


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
    """按命令能力筛归属环。

    规则（由宽到窄的反例都踩过）：
    1. 只要有任一部署**显式**宣告能覆盖该明文，就只在这些部署里取模；
       未宣告（``None`` / 旧版）的对端不再视为全能抢单——避免「一歌唱歌」
       被只有默认牛牛前缀或未升级的端 ``federate_owner_skip`` 掉。
    2. 若无人显式覆盖，但本机能力集能覆盖 → 本机独担。
    3. 仍无人 → 退回全员环（含未宣告端），兼容闲聊 / 未知命令。
    """
    text = (plain or "").strip()
    if not text:
        return active
    explicit: list[str] = []
    for dep in active:
        if dep == mine:
            caps: frozenset[str] | None = local_caps
        else:
            if dep not in _cache_deployment_capabilities:
                # 缓存未收录：与「字段缺失」一样视为未宣告，不进显式环
                continue
            caps = _cache_deployment_capabilities.get(dep)
            if caps is None:
                continue
        if command_capability_covers_plaintext(caps, text):
            explicit.append(dep)
    if explicit:
        return explicit
    if command_capability_covers_plaintext(local_caps, text):
        return [mine]
    return active


def _deployment_present_in_group(dep: str, group_id: int, *, mine: str) -> bool:
    if dep == mine:
        return True
    if dep not in _cache_deployment_present_groups:
        return True
    present = _cache_deployment_present_groups[dep]
    if present is None:
        return True
    return int(group_id) in present


def _present_owner_ring(capable: list[str], *, group_id: int, mine: str) -> list[str]:
    present = [dep for dep in capable if _deployment_present_in_group(dep, group_id, mine=mine)]
    if present:
        return present
    if mine in capable:
        return [mine]
    return capable


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
    capable = _capable_owner_ring(active, mine=deployment_id, plain=plain, local_caps=local_caps)
    ring = _present_owner_ring(capable, group_id=int(group_id), mine=deployment_id)
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


def should_yield_federate_ingress_for_peer_command(
    group_id: int,
    *,
    plain: str | None = None,
) -> bool:
    """本机无能力、但对端显式宣告能覆盖且在本群在场时，不参与联邦抢占。

    典型坑：对端装了决斗、本机没有 → 本机 ``legacy_command_traffic`` 为假，
    会绕过命令归属直接去抢 ``federate_ingress``，抢走后无 matcher，有能力的端又输掉 claim。
    """
    if not federate_ingress_active():
        return False
    if not _cache_deployment_ids:
        return False
    text = (plain or "").strip()
    if not text:
        return False
    local_caps = collect_local_federate_command_capabilities()
    if command_capability_covers_plaintext(local_caps, text):
        return False
    mine = load_or_create_deployment_id().strip().lower()
    if not mine:
        return False
    for dep in _cache_deployment_ids:
        if dep == mine:
            continue
        if dep not in _cache_deployment_capabilities:
            continue
        caps = _cache_deployment_capabilities.get(dep)
        if caps is None:
            continue
        if not command_capability_covers_plaintext(caps, text):
            continue
        if not _deployment_present_in_group(dep, int(group_id), mine=mine):
            continue
        return True
    return False


async def sync_federate_peer_bot_roster() -> None:
    global _cache_ids, _cache_deployment_capability_protocols, _cache_deployment_present_groups, _cache_updated_mono
    if not federate_ingress_active():
        _cache_ids = frozenset()
        _cache_deployment_capability_protocols = {}
        _cache_deployment_present_groups = {}
        _cache_updated_mono = time.monotonic()
        return
    await asyncio.to_thread(publish_local_federate_peer_bot_ids_sync)
    peer_ids = await asyncio.to_thread(refresh_federate_peer_bot_ids_sync)
    log_incompatible_federate_command_capability_peers()
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
