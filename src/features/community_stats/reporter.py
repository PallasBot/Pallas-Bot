"""组装心跳负载并 POST 至社区统计中心。"""

from __future__ import annotations

import time

import httpx
from nonebot import logger

from src.features.community_stats.config import CommunityStatsConfig, get_community_stats_config
from src.features.community_stats.endpoints import (
    FALLBACK_HEARTBEAT,
    PRIMARY_HEARTBEAT,
    heartbeat_urls_for_config,
    is_auto_endpoint_mode,
)
from src.features.community_stats.store import (
    load_or_create_deployment_id,
    save_heartbeat_endpoint,
    touch_primary_probe_unix,
)
from src.features.message_scrub.quiet_http_loggers import scrub_http_log_noise
from src.foundation.bot_version import get_pallas_bot_version_for_reporting
from src.platform.bot_runtime.roles import is_sharded_worker
from src.platform.multi_bot.fleet import get_catalog_bot_ids
from src.platform.shard.registry.config import is_sharding_active
from src.platform.shard.registry.store import get_shard_registry, is_test_shard_record

_HTTP_TIMEOUT_SEC = 15.0
_PROBE_TIMEOUT_SEC = 8.0


def should_run_community_stats_reporter() -> bool:
    if is_sharded_worker():
        return False
    return get_community_stats_config().enabled


def build_heartbeat_payload() -> dict[str, object]:
    from src.platform.shard.presence import count_connected_bots_for_reporting

    cfg = get_community_stats_config()
    online_bots = count_connected_bots_for_reporting()
    catalog_bots = len(get_catalog_bot_ids())
    sharded = is_sharding_active()
    shard_workers = 0
    if sharded:
        reg = get_shard_registry()
        shard_workers = len([s for s in reg.shards if not is_test_shard_record(s, reg)])
    payload: dict[str, object] = {
        "deployment_id": load_or_create_deployment_id(),
        "ts": int(time.time()),
        "version": get_pallas_bot_version_for_reporting(),
        "online_bots": online_bots,
        "catalog_bots": catalog_bots,
        "sharded": sharded,
        "shard_workers": shard_workers if sharded else None,
    }
    if cfg.roster_public:
        from src.features.community_stats.roster import build_public_roster_entries

        payload["roster_public"] = True
        payload["roster_show_qq"] = cfg.roster_public_qq
        payload["roster_show_profile"] = cfg.roster_public_profile
        payload["roster"] = build_public_roster_entries()
    else:
        payload["roster_public"] = False
    return payload


def _headers(cfg: CommunityStatsConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = (cfg.token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _post_heartbeat(
    client: httpx.AsyncClient,
    endpoint: str,
    *,
    payload: dict[str, object],
    cfg: CommunityStatsConfig,
    timeout_sec: float,
) -> bool:
    resp = await client.post(endpoint, json=payload, headers=_headers(cfg), timeout=timeout_sec)
    if resp.status_code == 200:
        save_heartbeat_endpoint(endpoint)
        logger.debug("community_stats: heartbeat ok deployment_id={} endpoint={}", payload["deployment_id"], endpoint)
        return True
    if resp.status_code == 429:
        logger.warning("community_stats: heartbeat rate limited (429) endpoint={}", endpoint)
    else:
        logger.warning(
            "community_stats: heartbeat HTTP {} endpoint={} body={}",
            resp.status_code,
            endpoint,
            (resp.text or "")[:200],
        )
    return False


async def send_community_stats_heartbeat() -> bool:
    cfg = get_community_stats_config()
    urls = heartbeat_urls_for_config(cfg)
    if not urls:
        logger.warning("community_stats: 无可用 endpoint，跳过上报")
        return False
    if is_auto_endpoint_mode(cfg) and urls[0] == PRIMARY_HEARTBEAT:
        touch_primary_probe_unix()
    payload = build_heartbeat_payload()
    try:
        async with scrub_http_log_noise():
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
                for i, endpoint in enumerate(urls):
                    timeout = _PROBE_TIMEOUT_SEC if i == 0 and len(urls) > 1 else _HTTP_TIMEOUT_SEC
                    try:
                        if await _post_heartbeat(client, endpoint, payload=payload, cfg=cfg, timeout_sec=timeout):
                            if is_auto_endpoint_mode(cfg) and endpoint == FALLBACK_HEARTBEAT and i > 0:
                                logger.info("community_stats: 正式域名暂不可用，已使用备用入口（备案通过后将自动切回）")
                            return True
                    except httpx.HTTPError as e:
                        logger.warning(f"community_stats: heartbeat failed endpoint={endpoint}: {e}")
    except httpx.HTTPError as e:
        logger.warning(f"community_stats: heartbeat failed: {e}")
    return False
