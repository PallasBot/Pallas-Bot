"""组装心跳负载并 POST 至社区统计中心。"""

from __future__ import annotations

import time

import httpx
from nonebot import logger

from pallas.core.foundation.bot_version import get_pallas_bot_version_for_reporting
from pallas.core.platform.bot_runtime.roles import is_sharded_worker
from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids
from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.registry.store import get_shard_registry, is_test_shard_record
from pallas.product.community_stats.config import CommunityStatsConfig, get_community_stats_config
from pallas.product.community_stats.endpoints import (
    FALLBACK_HEARTBEAT,
    PRIMARY_HEARTBEAT,
    heartbeat_urls_for_config,
    is_auto_endpoint_mode,
)
from pallas.product.community_stats.store import (
    load_or_create_deployment_id,
    save_heartbeat_endpoint,
    touch_primary_probe_unix,
)
from pallas.product.message_scrub.quiet_http_loggers import scrub_http_log_noise

_HTTP_TIMEOUT_SEC = 15.0
_PROBE_TIMEOUT_SEC = 8.0


def should_run_community_stats_reporter() -> bool:
    if is_sharded_worker():
        return False
    return get_community_stats_config().enabled


def build_heartbeat_payload(*, show_qq_by_account: dict[int, bool] | None = None) -> dict[str, object]:
    from pallas.core.platform.shard.presence import count_connected_bots_for_reporting

    cfg = get_community_stats_config()
    online_bots = count_connected_bots_for_reporting()
    catalog_bots = len(get_catalog_bot_ids())
    sharded = shard_ctx.sharding_active()
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
        from pallas.product.community_stats.roster import build_public_roster_entries

        payload["roster_public"] = True
        payload["roster_show_qq"] = cfg.roster_public_qq
        payload["roster_show_profile"] = cfg.roster_public_profile
        payload["roster"] = build_public_roster_entries(show_qq_by_account=show_qq_by_account)
    else:
        payload["roster_public"] = False
    return payload


async def maybe_build_corpus_hot_snapshot(cfg: CommunityStatsConfig) -> dict[str, object] | None:
    from pallas.product.community_stats.store import _read_state_raw, touch_corpus_hot_snapshot_unix
    from pallas.product.corpus.config import community_contribute_enabled
    from pallas.product.corpus.local_hot import build_corpus_hot_snapshot_items

    if not community_contribute_enabled():
        return None
    now = int(time.time())
    last = int(_read_state_raw().get("corpus_hot_snapshot_unix") or 0)
    if now - last < max(300, int(cfg.corpus_hot_snapshot_interval_sec)):
        return None
    try:
        items = await build_corpus_hot_snapshot_items()
    except Exception as e:
        logger.debug("community_stats: corpus hot snapshot build failed: {}", e)
        return None
    if not items:
        return None
    touch_corpus_hot_snapshot_unix(now)
    return {"as_of": now, "items": items[:40]}


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
        logger.warning("community_stats: no endpoint configured, skip heartbeat")
        return False
    if is_auto_endpoint_mode(cfg) and urls[0] == PRIMARY_HEARTBEAT:
        touch_primary_probe_unix()
    show_qq_by_account: dict[int, bool] | None = None
    if cfg.roster_public:
        from pallas.core.foundation.db.pallas_console_data import bot_community_roster_show_qq_by_accounts
        from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids

        inventory = get_catalog_bot_ids()
        if inventory:
            show_qq_by_account = await bot_community_roster_show_qq_by_accounts(list(inventory))
    payload = build_heartbeat_payload(show_qq_by_account=show_qq_by_account)
    snapshot = await maybe_build_corpus_hot_snapshot(cfg)
    if snapshot is not None:
        payload["corpus_hot_snapshot"] = snapshot
    try:
        async with scrub_http_log_noise():
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
                for i, endpoint in enumerate(urls):
                    timeout = _PROBE_TIMEOUT_SEC if i == 0 and len(urls) > 1 else _HTTP_TIMEOUT_SEC
                    try:
                        if await _post_heartbeat(client, endpoint, payload=payload, cfg=cfg, timeout_sec=timeout):
                            if is_auto_endpoint_mode(cfg) and endpoint == FALLBACK_HEARTBEAT and i > 0:
                                logger.info("community_stats: primary endpoint unavailable, using fallback")
                            return True
                    except httpx.HTTPError as e:
                        logger.warning(f"community_stats: heartbeat failed endpoint={endpoint}: {e}")
    except httpx.HTTPError as e:
        logger.warning(f"community_stats: heartbeat failed: {e}")
    return False
