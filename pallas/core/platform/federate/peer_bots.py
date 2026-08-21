"""协同池内其它部署牛牛名册。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
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
from pallas.core.platform.ingress.fanout_bypass import GREETING_CALL_NAMES
from pallas.core.platform.ingress.plugin_command_plaintext import (
    _extract_literal_prefix,
    _iter_trigger_parts,
    extract_command_prefixes_from_menu_data,
)
from pallas.core.platform.ingress.route_index import (
    extract_exact_plaintexts_from_menu_data,
    extract_explicit_route_strings,
)
from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids
from pallas.core.platform.multi_bot.group_admin_capability import (
    local_group_admin_bot_ids,
    local_group_admin_observation_complete,
)
from pallas.core.platform.multi_bot.group_online_cache import (
    NS_LOCAL_CONNECTED,
    get_cached_group_bot_ids,
)
from pallas.product.community_stats.store import load_or_create_deployment_id

_PEER_KEY_SEGMENT = "peer_bots"
_PRESENT_GROUPS_KEY_SEGMENT = "present_groups"
COMMAND_CAPABILITY_PROTOCOL_VERSION = 2
INGRESS_PROTOCOL_VERSION = 2
_PUBLISH_TTL_SEC = max(60, int(os.getenv("PALLAS_FEDERATE_PEER_BOT_TTL_SEC", "180")))
_REFRESH_INTERVAL_SEC = max(15.0, float(os.getenv("PALLAS_FEDERATE_PEER_BOT_REFRESH_SEC", "60")))
_PRESENT_GROUP_WINDOW_SEC = max(_PUBLISH_TTL_SEC, int(os.getenv("PALLAS_FEDERATE_PRESENT_GROUP_WINDOW_SEC", "300")))
_PRESENT_GROUP_PUBLISH_CAP = max(64, int(os.getenv("PALLAS_FEDERATE_PRESENT_GROUP_PUBLISH_CAP", "2000")))
_NICKNAME_CACHE_TTL_SEC = max(60.0, float(os.getenv("PALLAS_FEDERATE_NICKNAME_CACHE_SEC", "600")))
_NICKNAME_FAILURE_CACHE_TTL_SEC = max(15.0, min(_NICKNAME_CACHE_TTL_SEC, 60.0))
_NICKNAME_CACHE_MAX_SIZE = max(1, int(os.getenv("PALLAS_FEDERATE_NICKNAME_CACHE_MAX_SIZE", "1024")))
_NICKNAME_QUERY_CONCURRENCY = 4
_NICKNAME_QUERY_TIMEOUT_SEC = 2.0
_cache_ids: frozenset[int] = frozenset()
_cache_deployment_ids: frozenset[str] = frozenset()
# None = 对端未宣告（旧版），视为全能；frozenset = 明确能力集
_cache_deployment_capabilities: dict[str, frozenset[str] | None] = {}
# None = 对端未宣告命令权限等级（旧版），视为 everyone 兼容
_cache_deployment_permission_levels: dict[str, dict[str, str] | None] = {}
# None = 旧端未声明命令能力协议版本。
_cache_deployment_capability_protocols: dict[str, int | None] = {}
_cache_deployment_ingress_capabilities: dict[str, frozenset[str] | None] = {}
_cache_deployment_ingress_protocols: dict[str, int | None] = {}
# None = 对端未宣告在场群（旧版），视为可能在场；frozenset = 近期在场群
_cache_deployment_present_groups: dict[str, frozenset[int] | None] = {}
_cache_deployment_group_admin_bot_ids: dict[str, dict[int, frozenset[int]] | None] = {}
_cache_deployment_rosters: dict[str, FederatePeerBotRoster] = {}
_cache_local_roster: FederatePeerBotRoster | None = None
_local_present_groups: dict[int, float] = {}
_local_public_online_nickname_cache: dict[int, tuple[float, str]] = {}
# 本地命令元数据收集缓存：插件加载/热载时失效
_local_command_capabilities_cache: frozenset[str] | None = None
_local_command_permission_levels_cache: dict[str, str] | None = None
_local_command_plaintext_to_id_cache: dict[str, str] | None = None
_cache_updated_mono: float = 0.0
_sync_task: asyncio.Task[None] | None = None
_last_incompatible_capability_peers: tuple[str, ...] = ()
_last_incompatible_ingress_peers: tuple[str, ...] = ()


@dataclass(frozen=True)
class FederatePeerBotRoster:
    deployment_id: str
    deployment_name: str
    bot_ids: frozenset[int]
    # None 表示对端尚未发布在线态，不能误判为全部离线。
    online_bot_ids: frozenset[int] | None
    public_bot_ids: frozenset[int]
    public_online_bot_names: dict[int, str] = field(default_factory=dict)


def clear_federate_peer_bot_cache_for_tests() -> None:
    global \
        _cache_deployment_capabilities, \
        _cache_deployment_capability_protocols, \
        _cache_deployment_ingress_capabilities, \
        _cache_deployment_ingress_protocols, \
        _cache_deployment_ids, \
        _cache_deployment_present_groups, \
        _cache_deployment_group_admin_bot_ids, \
        _cache_deployment_permission_levels, \
        _cache_deployment_rosters, \
        _cache_local_roster, \
        _cache_ids, \
        _local_public_online_nickname_cache, \
        _local_command_capabilities_cache, \
        _local_command_permission_levels_cache, \
        _local_command_plaintext_to_id_cache, \
        _cache_updated_mono, \
        _local_present_groups, \
        _sync_task, \
        _last_incompatible_capability_peers, \
        _last_incompatible_ingress_peers
    _cache_ids = frozenset()
    _cache_deployment_ids = frozenset()
    _cache_deployment_capabilities = {}
    _cache_deployment_capability_protocols = {}
    _cache_deployment_ingress_capabilities = {}
    _cache_deployment_ingress_protocols = {}
    _cache_deployment_present_groups = {}
    _cache_deployment_group_admin_bot_ids = {}
    _cache_deployment_permission_levels = {}
    _cache_deployment_rosters = {}
    _cache_local_roster = None
    _local_present_groups = {}
    _local_public_online_nickname_cache = {}
    _local_command_capabilities_cache = None
    _local_command_permission_levels_cache = None
    _local_command_plaintext_to_id_cache = None
    _cache_updated_mono = 0.0
    _sync_task = None
    _last_incompatible_capability_peers = ()
    _last_incompatible_ingress_peers = ()


def clear_local_federate_metadata_cache() -> None:
    """插件加载/热载后失效本地命令元数据收集缓存。"""
    global \
        _local_command_capabilities_cache, \
        _local_command_permission_levels_cache, \
        _local_command_plaintext_to_id_cache
    _local_command_capabilities_cache = None
    _local_command_permission_levels_cache = None
    _local_command_plaintext_to_id_cache = None


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
    global _local_command_capabilities_cache
    if _local_command_capabilities_cache is not None:
        return _local_command_capabilities_cache
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
    from pallas.core.platform.ingress.matcher_command_words import collect_command_words_from_matchers

    caps.update(collect_command_words_from_matchers())
    result = frozenset(caps)
    _local_command_capabilities_cache = result
    return result


def collect_local_command_permission_levels() -> dict[str, str]:
    """本机已加载命令的当前权限等级（默认 + WebUI 覆盖），供协同心跳宣告。"""
    global _local_command_permission_levels_cache
    if _local_command_permission_levels_cache is not None:
        return _local_command_permission_levels_cache
    from pallas.core.perm.config import get_cmd_perm_config
    from pallas.core.perm.registry import resolved_level
    from pallas.core.perm.schema import merged_default_levels

    overrides = get_cmd_perm_config().command_permission_overrides
    levels = {cid: resolved_level(cid, overrides) for cid in merged_default_levels()}
    _local_command_permission_levels_cache = levels
    return levels


def collect_local_command_plaintext_to_id() -> dict[str, str]:
    """本机 menu_data 声明的命令明文（exact / prefix）到 command_id 映射。

    供归属判定把消息明文解析为命令 ID，进而比较各部署的权限等级。
    """
    global _local_command_plaintext_to_id_cache
    if _local_command_plaintext_to_id_cache is not None:
        return _local_command_plaintext_to_id_cache
    from nonebot import get_loaded_plugins

    mapping: dict[str, str] = {}
    try:
        plugins = get_loaded_plugins()
    except Exception:
        return mapping
    for plugin in plugins:
        meta = getattr(plugin, "metadata", None)
        extra = getattr(meta, "extra", None) if meta is not None else None
        if not isinstance(extra, dict):
            continue
        menu_data = extra.get("menu_data")
        if not isinstance(menu_data, list):
            continue
        for item in menu_data:
            command_id = str(item.get("command_permission") or item.get("command_id") or "").strip()
            if not command_id:
                continue
            trigger = str(item.get("trigger_condition") or "").strip()
            if not trigger:
                continue
            for part in _iter_trigger_parts(trigger):
                text = part.strip()
                if not text or any(ch in text for ch in "〈<[@+"):
                    continue
                if len(text) >= 2 and text not in mapping:
                    mapping[text] = command_id
                prefix = _extract_literal_prefix(part)
                if prefix and prefix not in mapping:
                    mapping[prefix] = command_id
    _local_command_plaintext_to_id_cache = mapping
    return mapping


def local_federate_deployment_name() -> str:
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    return str(repo_env_raw_value("PALLAS_FEDERATE_DEPLOYMENT_NAME") or "").strip()


def collect_local_federate_online_bot_ids() -> frozenset[int]:
    from pallas.core.platform.shard import context as shard_ctx

    if shard_ctx.sharding_active():
        from pallas.core.platform.shard.presence import get_cluster_online_bot_ids

        return get_cluster_online_bot_ids()
    from pallas.core.platform.multi_bot.connected_roster import connected_bot_ids

    return frozenset(int(qq) for qq in connected_bot_ids())


async def collect_local_federate_public_bot_ids(bot_ids: frozenset[int]) -> frozenset[int]:
    """读取允许在协同群内展示 QQ 的本地牛牛。"""
    if not bot_ids:
        return frozenset()
    try:
        from pallas.product.community_stats.config import get_community_stats_config

        if not get_community_stats_config().roster_public_qq:
            return frozenset()
        from pallas.core.foundation.db.pallas_console_data import bot_community_roster_show_qq_by_accounts

        allowed = await bot_community_roster_show_qq_by_accounts(list(bot_ids))
        return frozenset(qq for qq in bot_ids if allowed.get(qq, True))
    except Exception:
        # 展示权限读取失败时宁可不公开，下一次心跳会重试。
        return frozenset()


def collect_local_federate_public_online_bot_names(
    online_bot_ids: frozenset[int],
    public_bot_ids: frozenset[int],
) -> dict[int, str]:
    """读取允许公开的在线牛牛显示名，供协同名册快照使用。"""
    try:
        from pallas.console.webui.protocol_accounts import protocol_account_display_names

        display_names = protocol_account_display_names()
    except Exception:
        return {}
    visible_ids = online_bot_ids & public_bot_ids
    return {qq: name for qq in visible_ids if (name := str(display_names.get(str(qq)) or "").strip())}


def _prune_local_public_online_nickname_cache(now: float) -> None:
    expired = [qq for qq, (expires_at, _) in _local_public_online_nickname_cache.items() if expires_at <= now]
    for qq in expired:
        _local_public_online_nickname_cache.pop(qq, None)
    overflow = len(_local_public_online_nickname_cache) - _NICKNAME_CACHE_MAX_SIZE
    if overflow <= 0:
        return
    oldest = sorted(_local_public_online_nickname_cache, key=lambda qq: _local_public_online_nickname_cache[qq][0])
    for qq in oldest[:overflow]:
        _local_public_online_nickname_cache.pop(qq, None)


async def collect_local_federate_public_online_bot_names_async(
    online_bot_ids: frozenset[int],
    public_bot_ids: frozenset[int],
) -> dict[int, str]:
    names = collect_local_federate_public_online_bot_names(online_bot_ids, public_bot_ids)
    visible_ids = online_bot_ids & public_bot_ids
    now = time.monotonic()
    _prune_local_public_online_nickname_cache(now)
    pending: list[int] = []
    for qq in visible_ids:
        if qq in names:
            continue
        cached = _local_public_online_nickname_cache.get(qq)
        if cached is not None and cached[0] > now:
            if cached[1]:
                names[qq] = cached[1]
            continue
        pending.append(qq)
    if not pending:
        return names

    from pallas.product.persona.self_identity import resolve_login_nickname

    sem = asyncio.Semaphore(_NICKNAME_QUERY_CONCURRENCY)

    async def resolve_one(qq: int) -> tuple[int, str]:
        async with sem:
            try:
                nickname = await asyncio.wait_for(
                    resolve_login_nickname(qq),
                    timeout=_NICKNAME_QUERY_TIMEOUT_SEC,
                )
            except Exception:
                nickname = ""
            return qq, str(nickname or "").strip()

    for qq, nickname in await asyncio.gather(*(resolve_one(qq) for qq in pending)):
        ttl = _NICKNAME_CACHE_TTL_SEC if nickname else _NICKNAME_FAILURE_CACHE_TTL_SEC
        _local_public_online_nickname_cache[qq] = (time.monotonic() + ttl, nickname)
        if nickname:
            names[qq] = nickname
    _prune_local_public_online_nickname_cache(time.monotonic())
    return names


def _capability_is_call_name(token: str) -> bool:
    """唤名能力（裸「牛牛」/「帕拉斯」等 greeting 唤名）只精确匹配。

    这类 token 若作前缀覆盖，会让本机对一切 ``牛牛*`` 命令声称有能力，
    配合 prefer_local_owner 固定本机当 owner 后，本机无 matcher 会落入 LLM 兜底。
    """
    return token in GREETING_CALL_NAMES


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
        if text == token:
            return True
        if matches_command_prefix(text, token) and not _capability_is_call_name(token):
            return True
    return False


def federate_peer_declared_command_plaintext(plain: str) -> bool:
    """任一联邦对端显式宣告的命令能力是否覆盖该明文。

    供命令车道识别：本机未装某命令、但对端显式宣告有时（如对端装了画画、本机没有），
    本机也把它当命令流量进归属环，让有能力的一方接手，而不是落入 llm_chat 兜底。
    """
    if not federate_ingress_active():
        return False
    if not _cache_deployment_ids:
        return False
    text = (plain or "").strip()
    if not text:
        return False
    for dep in _cache_deployment_ids:
        caps = _cache_deployment_capabilities.get(dep)
        if caps is None:
            continue
        if command_capability_covers_plaintext(caps, text):
            return True
    return False


def get_federate_peer_command_capabilities(deployment_id: str) -> frozenset[str] | None:
    key = deployment_id.strip().lower()
    if key not in _cache_deployment_capabilities:
        return None
    return _cache_deployment_capabilities[key]


def get_federate_peer_command_capability_protocol(deployment_id: str) -> int | None:
    return _cache_deployment_capability_protocols.get(deployment_id.strip().lower())


def get_federate_peer_command_permission_levels(deployment_id: str) -> dict[str, str] | None:
    return _cache_deployment_permission_levels.get(deployment_id.strip().lower())


def get_incompatible_federate_command_capability_peers() -> tuple[str, ...]:
    return tuple(
        sorted(
            deployment_id
            for deployment_id in _cache_deployment_ids
            if _cache_deployment_capability_protocols.get(deployment_id) != COMMAND_CAPABILITY_PROTOCOL_VERSION
        )
    )


def collect_local_federate_ingress_capabilities() -> frozenset[str]:
    return frozenset({"command", "llm_alias", "hosted_activity"})


def get_federate_peer_ingress_capabilities(deployment_id: str) -> frozenset[str] | None:
    return _cache_deployment_ingress_capabilities.get(deployment_id.strip().lower())


def get_federate_peer_ingress_protocol(deployment_id: str) -> int | None:
    return _cache_deployment_ingress_protocols.get(deployment_id.strip().lower())


def get_incompatible_federate_ingress_peers() -> tuple[str, ...]:
    return tuple(
        sorted(
            deployment_id
            for deployment_id in _cache_deployment_ids
            if _cache_deployment_ingress_protocols.get(deployment_id) != INGRESS_PROTOCOL_VERSION
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


def publish_local_federate_peer_bot_ids_sync(
    bot_ids: set[int] | frozenset[int] | None = None,
    *,
    public_bot_ids: frozenset[int] | None = None,
    public_online_bot_names: dict[int, str] | None = None,
) -> bool:
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is None or not prefix or not deployment_id:
        return False
    ids = sorted(int(qq) for qq in (bot_ids if bot_ids is not None else get_catalog_bot_ids()))
    id_set = frozenset(ids)
    online_ids = sorted(id_set & collect_local_federate_online_bot_ids())
    public_ids = sorted(id_set & (public_bot_ids or frozenset()))
    public_names = public_online_bot_names
    if public_names is None:
        public_names = collect_local_federate_public_online_bot_names(
            frozenset(online_ids),
            frozenset(public_ids),
        )
    capabilities = sorted(collect_local_federate_command_capabilities())
    permission_levels = collect_local_command_permission_levels()
    present_groups = collect_local_present_group_ids()
    group_admin_bot_ids = {
        str(group_id): sorted(admin_ids)
        for group_id in present_groups
        if (admin_ids := get_local_group_admin_bot_ids(group_id)) is not None
    }
    payload_obj: dict[str, Any] = {
        "deployment_id": deployment_id,
        "deployment_name": local_federate_deployment_name(),
        "bot_ids": ids,
        "online_bot_ids": online_ids,
        "public_bot_ids": public_ids,
        "public_online_bot_names": {
            str(qq): name
            for qq, name in sorted(public_names.items())
            if qq in online_ids and qq in public_ids and name.strip()
        },
        "updated_at": int(time.time()),
        "present_group_ids": present_groups,
        "command_capability_protocol": COMMAND_CAPABILITY_PROTOCOL_VERSION,
        "ingress_protocol": INGRESS_PROTOCOL_VERSION,
        "ingress_capabilities": sorted(collect_local_federate_ingress_capabilities()),
    }
    if group_admin_bot_ids:
        payload_obj["group_admin_bot_ids"] = group_admin_bot_ids
    # 插件尚未加载时能力为空：不写字段，避免被当成「零能力」抢走全部命令归属
    if capabilities:
        payload_obj["command_capabilities"] = capabilities
    # 权限等级全量宣告：旧端（无该字段）视为 everyone 兼容，不破坏既有部署
    if permission_levels:
        payload_obj["command_permission_levels"] = dict(sorted(permission_levels.items()))

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


def _parse_command_permission_levels(data: dict[str, Any]) -> dict[str, str] | None:
    """解析对端宣告的命令权限等级；未宣告（旧版）返回 None。"""
    raw = data.get("command_permission_levels")
    if not isinstance(raw, dict):
        return None
    levels: dict[str, str] = {}
    for cid, level in raw.items():
        text = str(level).strip().lower()
        if text:
            levels[str(cid).strip()] = text
    return levels or None


def _parse_ingress_capabilities(data: dict[str, Any]) -> frozenset[str] | None:
    if "ingress_capabilities" not in data:
        return None
    raw = data.get("ingress_capabilities")
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(str(item).strip() for item in raw if str(item).strip())


def _parse_ingress_protocol(data: dict[str, Any]) -> int | None:
    raw = data.get("ingress_protocol")
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


def _parse_group_admin_bot_ids(data: dict[str, Any]) -> dict[int, frozenset[int]] | None:
    if "group_admin_bot_ids" not in data:
        return None
    raw = data.get("group_admin_bot_ids")
    if not isinstance(raw, dict):
        return None
    groups: dict[int, frozenset[int]] = {}
    for raw_group_id, raw_bot_ids in raw.items():
        if not str(raw_group_id).isdigit() or not isinstance(raw_bot_ids, (list, tuple, set, frozenset)):
            continue
        groups[int(raw_group_id)] = frozenset(int(bot_id) for bot_id in raw_bot_ids if str(bot_id).isdigit())
    return groups


def get_federate_peer_group_admin_bot_ids(
    deployment_id: str,
    group_id: int,
) -> frozenset[int] | None:
    groups = _cache_deployment_group_admin_bot_ids.get(deployment_id.strip().lower())
    if groups is None:
        return None
    return groups.get(int(group_id))


def get_local_group_admin_bot_ids(group_id: int) -> frozenset[int] | None:
    local_bot_ids = get_cached_group_bot_ids(group_id, namespace=NS_LOCAL_CONNECTED)
    if local_bot_ids is None or not local_group_admin_observation_complete(group_id, local_bot_ids):
        return None
    return local_group_admin_bot_ids(group_id)


def group_admin_bot_ids_by_deployment(
    group_id: int,
    deployment_ids: list[str] | tuple[str, ...] | frozenset[str],
) -> dict[str, frozenset[int] | None]:
    mine = load_or_create_deployment_id().strip().lower()
    result: dict[str, frozenset[int] | None] = {}
    for deployment_id in deployment_ids:
        key = deployment_id.strip().lower()
        if key == mine:
            result[key] = get_local_group_admin_bot_ids(group_id)
        else:
            result[key] = get_federate_peer_group_admin_bot_ids(key, group_id)
    return result


def _parse_bot_ids(data: dict[str, Any], key: str, *, missing_is_none: bool = False) -> frozenset[int] | None:
    if key not in data:
        return None if missing_is_none else frozenset()
    raw = data.get(key)
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(int(item) for item in raw if str(item).isdigit())


def _parse_public_online_bot_names(data: dict[str, Any], allowed_ids: frozenset[int]) -> dict[int, str]:
    raw = data.get("public_online_bot_names")
    if not isinstance(raw, dict):
        return {}
    names: dict[int, str] = {}
    for raw_qq, raw_name in raw.items():
        if not str(raw_qq).isdigit():
            continue
        qq = int(raw_qq)
        name = str(raw_name).strip()
        if qq in allowed_ids and name:
            names[qq] = name
    return names


def refresh_federate_peer_bot_ids_sync() -> frozenset[int]:
    global \
        _cache_deployment_capabilities, \
        _cache_deployment_capability_protocols, \
        _cache_deployment_ingress_capabilities, \
        _cache_deployment_ingress_protocols, \
        _cache_deployment_ids, \
        _cache_deployment_permission_levels, \
        _cache_deployment_present_groups, \
        _cache_deployment_group_admin_bot_ids, \
        _cache_deployment_rosters, \
        _cache_ids, \
        _cache_updated_mono
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    deployment_id = load_or_create_deployment_id().strip().lower()
    if client is None or not prefix or not deployment_id:
        _cache_ids = frozenset()
        _cache_deployment_ids = frozenset()
        _cache_deployment_capabilities = {}
        _cache_deployment_ingress_capabilities = {}
        _cache_deployment_ingress_protocols = {}
        _cache_deployment_permission_levels = {}
        _cache_deployment_present_groups = {}
        _cache_deployment_group_admin_bot_ids = {}
        _cache_deployment_rosters = {}
        _cache_updated_mono = time.monotonic()
        return _cache_ids
    peer_deployment_ids: set[str] = set()
    peer_ids: set[int] = set()
    peer_capabilities: dict[str, frozenset[str] | None] = {}
    peer_protocols: dict[str, int | None] = {}
    peer_permission_levels: dict[str, dict[str, str] | None] = {}
    peer_ingress_capabilities: dict[str, frozenset[str] | None] = {}
    peer_ingress_protocols: dict[str, int | None] = {}
    peer_present: dict[str, frozenset[int] | None] = {}
    peer_group_admin: dict[str, dict[int, frozenset[int]] | None] = {}
    peer_rosters: dict[str, FederatePeerBotRoster] = {}
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
                peer_permission_levels[payload_deployment_id] = _parse_command_permission_levels(data)
                peer_ingress_capabilities[payload_deployment_id] = _parse_ingress_capabilities(data)
                peer_ingress_protocols[payload_deployment_id] = _parse_ingress_protocol(data)
                peer_present[payload_deployment_id] = _parse_present_group_ids(data)
                peer_group_admin[payload_deployment_id] = _parse_group_admin_bot_ids(data)
                bot_ids = _parse_bot_ids(data, "bot_ids") or frozenset()
                online_bot_ids = _parse_bot_ids(data, "online_bot_ids", missing_is_none=True)
                public_bot_ids = _parse_bot_ids(data, "public_bot_ids") or frozenset()
                public_online_ids = (online_bot_ids or frozenset()) & public_bot_ids & bot_ids
                peer_rosters[payload_deployment_id] = FederatePeerBotRoster(
                    deployment_id=payload_deployment_id,
                    deployment_name=str(data.get("deployment_name") or "").strip(),
                    bot_ids=bot_ids,
                    online_bot_ids=online_bot_ids,
                    public_bot_ids=public_bot_ids & bot_ids,
                    public_online_bot_names=_parse_public_online_bot_names(data, public_online_ids),
                )
                peer_ids.update(bot_ids)
    except Exception:
        return _cache_ids
    _cache_ids = frozenset(peer_ids)
    _cache_deployment_ids = frozenset(peer_deployment_ids)
    _cache_deployment_capabilities = peer_capabilities
    _cache_deployment_capability_protocols = peer_protocols
    _cache_deployment_permission_levels = peer_permission_levels
    _cache_deployment_ingress_capabilities = peer_ingress_capabilities
    _cache_deployment_ingress_protocols = peer_ingress_protocols
    _cache_deployment_present_groups = peer_present
    _cache_deployment_group_admin_bot_ids = peer_group_admin
    _cache_deployment_rosters = peer_rosters
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


def _federate_peer_shares_present_group(deployment_id: str) -> bool:
    """对端与本机是否在至少一个共同群里（均有号在场）。"""
    peer_groups = get_federate_peer_present_groups(deployment_id)
    if not peer_groups:
        return False
    local_groups = frozenset(collect_local_present_group_ids())
    return bool(peer_groups & local_groups)


def _federate_peer_display_label(deployment_id: str) -> str:
    roster = get_federate_peer_bot_roster(deployment_id)
    name = (roster.deployment_name if roster else "") or ""
    if name:
        return f"{name} ({deployment_id})"
    return deployment_id


def log_incompatible_federate_ingress_peers() -> None:
    global _last_incompatible_ingress_peers
    peers = tuple(dep for dep in get_incompatible_federate_ingress_peers() if _federate_peer_shares_present_group(dep))
    if peers == _last_incompatible_ingress_peers:
        return
    _last_incompatible_ingress_peers = peers
    if peers:
        logger.warning(
            "[联邦] 对端 {} 未支持统一 ingress 协议 v{}，且与本机在共同群；"
            "其定向命令/消息不再跨机协调，普通消息仍正常协调，请升级并重启这些部署",
            ", ".join(_federate_peer_display_label(dep) for dep in peers),
            INGRESS_PROTOCOL_VERSION,
        )


def get_federate_peer_bot_ids() -> frozenset[int]:
    return _cache_ids


def get_federate_peer_deployment_ids() -> frozenset[str]:
    return _cache_deployment_ids


def get_federate_peer_bot_roster(deployment_id: str) -> FederatePeerBotRoster | None:
    return _cache_deployment_rosters.get(deployment_id.strip().lower())


def get_federate_peer_bot_rosters() -> tuple[FederatePeerBotRoster, ...]:
    return tuple(_cache_deployment_rosters[key] for key in sorted(_cache_deployment_rosters))


async def _build_local_federate_bot_roster(*, resolve_login_nicknames: bool = True) -> FederatePeerBotRoster:
    deployment_id = load_or_create_deployment_id().strip().lower()
    bot_ids = get_catalog_bot_ids()
    public_bot_ids = await collect_local_federate_public_bot_ids(bot_ids)
    online_bot_ids = collect_local_federate_online_bot_ids() & bot_ids
    visible_online_ids = online_bot_ids & public_bot_ids & bot_ids
    if resolve_login_nicknames:
        public_online_bot_names = await collect_local_federate_public_online_bot_names_async(
            online_bot_ids,
            public_bot_ids & bot_ids,
        )
    else:
        public_online_bot_names = collect_local_federate_public_online_bot_names(
            online_bot_ids,
            public_bot_ids & bot_ids,
        )
    return FederatePeerBotRoster(
        deployment_id=deployment_id,
        deployment_name=local_federate_deployment_name() or f"部署 {deployment_id or '本机'}",
        bot_ids=bot_ids,
        online_bot_ids=online_bot_ids,
        public_bot_ids=public_bot_ids & bot_ids,
        public_online_bot_names={qq: name for qq, name in public_online_bot_names.items() if qq in visible_online_ids},
    )


async def get_federate_bot_rosters() -> tuple[FederatePeerBotRoster, ...]:
    global _cache_local_roster
    if _cache_local_roster is None:
        _cache_local_roster = await _build_local_federate_bot_roster(resolve_login_nicknames=False)
    return (_cache_local_roster, *get_federate_peer_bot_rosters())


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


def stable_group_owner_ring_index(group_id: int, ring_size: int) -> int:
    if ring_size <= 0:
        return 0
    digest = hashlib.blake2b(str(int(group_id)).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % ring_size


@dataclass(frozen=True)
class GroupAdminOwner:
    deployment_id: str
    bot_id: int


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


_PERMISSION_LEVEL_ORDER: tuple[str, ...] = (
    "everyone",
    "staff",
    "group_moderator",
    "bot_moderator",
    "superuser",
)


def _permission_level_rank(level: str) -> int:
    """权限宽松度排序：everyone 最宽松（所有人可用），superuser 最严格。"""
    text = (level or "everyone").strip().lower()
    try:
        return _PERMISSION_LEVEL_ORDER.index(text)
    except ValueError:
        return 0


def _command_permission_level_for_dep(dep: str, command_id: str, *, mine: str) -> str:
    """取某部署对某命令的权限等级；本机用本地生效等级，对端用宣告值，缺失视为 everyone。"""
    if dep == mine:
        return collect_local_command_permission_levels().get(command_id, "everyone")
    peer_levels = get_federate_peer_command_permission_levels(dep)
    if not peer_levels:
        return "everyone"
    return peer_levels.get(command_id, "everyone")


def _plaintext_to_command_id(text: str) -> str:
    """把消息明文解析为命令 ID：先精确，再按最长前缀。"""
    mapping = collect_local_command_plaintext_to_id()
    if not mapping or not text:
        return ""
    if text in mapping:
        return mapping[text]
    for key in sorted(mapping, key=len, reverse=True):
        if text[: len(key)].casefold() == key.casefold():
            return mapping[key]
    return ""


def _permission_owner_ring(
    active: list[str],
    *,
    mine: str,
    plain: str | None,
) -> list[str]:
    """在能力环内再按命令权限等级筛归属：等级最宽松的部署独占，严格端让位。

    场景：本机 bot_status.status=everyone、对端=bot_moderator 时，普通用户发「牛牛在吗」
    只有本机能执行；若取模轮到对端，对端会权限校验失败并落入 llm_chat 兜底。
    因此只保留权限最宽松的部署，宽松端永远能执行，严格端只在并列时才参与取模。

    兼容：环内任一部署未宣告权限等级（旧版）时不启用该过滤，保持旧取模行为，
    避免旧端被误判为 everyone 后抢走严格命令。
    """
    if len(active) <= 1:
        return active
    for dep in active:
        if dep == mine:
            continue
        if get_federate_peer_command_permission_levels(dep) is None:
            return active
    text = (plain or "").strip()
    if not text:
        return active
    command_id = _plaintext_to_command_id(text)
    if not command_id:
        return active
    best_rank = len(_PERMISSION_LEVEL_ORDER) + 1
    loosest: list[str] = []
    for dep in active:
        level = _command_permission_level_for_dep(dep, command_id, mine=mine)
        rank = _permission_level_rank(level)
        if rank < best_rank:
            best_rank = rank
            loosest = [dep]
        elif rank == best_rank:
            loosest.append(dep)
    if not loosest:
        return active
    return loosest


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
    capable = _permission_owner_ring(capable, mine=deployment_id, plain=plain)
    ring = _present_owner_ring(capable, group_id=int(group_id), mine=deployment_id)
    if federate_prefer_local_owner() and deployment_id in ring:
        return deployment_id
    idx = federate_group_owner_ring_index(int(group_id), len(ring), now=now)
    return ring[idx]


def federate_group_admin_owner(
    group_id: int,
    *,
    plain: str | None = None,
) -> GroupAdminOwner | None:
    deployment_id = load_or_create_deployment_id().strip().lower()
    if not deployment_id:
        return None
    active = sorted({deployment_id, *_cache_deployment_ids})
    local_caps = collect_local_federate_command_capabilities()
    capable = _capable_owner_ring(active, mine=deployment_id, plain=plain, local_caps=local_caps)
    capable = _permission_owner_ring(capable, mine=deployment_id, plain=plain)
    ring = _present_owner_ring(capable, group_id=int(group_id), mine=deployment_id)
    observed = group_admin_bot_ids_by_deployment(int(group_id), ring)
    if any(bot_ids is None for bot_ids in observed.values()):
        return None
    eligible_deployments = sorted(dep for dep, bot_ids in observed.items() if bot_ids)
    if not eligible_deployments:
        return None
    owner_deployment = eligible_deployments[stable_group_owner_ring_index(int(group_id), len(eligible_deployments))]
    bot_ids = sorted(observed[owner_deployment] or ())
    return GroupAdminOwner(
        deployment_id=owner_deployment,
        bot_id=bot_ids[stable_group_owner_ring_index(int(group_id), len(bot_ids))],
    )


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
    global \
        _cache_ids, \
        _cache_deployment_capability_protocols, \
        _cache_deployment_ingress_capabilities, \
        _cache_deployment_ingress_protocols, \
        _cache_deployment_present_groups, \
        _cache_local_roster, \
        _cache_deployment_rosters, \
        _cache_updated_mono
    if not federate_ingress_active():
        _cache_ids = frozenset()
        _cache_deployment_capability_protocols = {}
        _cache_deployment_ingress_capabilities = {}
        _cache_deployment_ingress_protocols = {}
        _cache_deployment_present_groups = {}
        _cache_local_roster = None
        _cache_deployment_rosters = {}
        _cache_updated_mono = time.monotonic()
        return
    local_roster = await _build_local_federate_bot_roster(resolve_login_nicknames=True)
    _cache_local_roster = local_roster
    await asyncio.to_thread(
        publish_local_federate_peer_bot_ids_sync,
        local_roster.bot_ids,
        public_bot_ids=local_roster.public_bot_ids,
        public_online_bot_names=local_roster.public_online_bot_names,
    )
    peer_ids = await asyncio.to_thread(refresh_federate_peer_bot_ids_sync)
    log_incompatible_federate_command_capability_peers()
    log_incompatible_federate_ingress_peers()
    logger.debug("Federate peer bots synchronized [{}] peers.", len(peer_ids))


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
