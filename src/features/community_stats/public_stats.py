"""拉取社区统计中心公开聚合指标（供控制台代理）。"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from nonebot import logger

from src.features.community_stats.config import get_community_stats_config
from src.features.community_stats.endpoints import monitor_overview_urls_for_config, stats_urls_for_config
from src.features.message_scrub.quiet_http_loggers import scrub_http_log_noise

_MONITOR_TIMEOUT_SEC = 5.0
_STATS_TIMEOUT_SEC = 12.0
_REQUIRED_KEYS = ("deployments_total", "deployments_online", "bots_online_sum")
_CORPUS_KEYS = (
    "contexts_total",
    "answers_total",
    "enrollments_total",
    "contribute_enabled_total",
    "answer_hits_sum",
    "enrollments_online",
    "enrollments_recent_24h",
    "read_enabled_total",
)
_DEPLOYMENT_EXTRA_KEYS = (
    "catalog_bots_online_sum",
    "active_recent_24h",
)
_FEDERATION_KEYS = (
    "members_total",
    "members_online",
    "members_recent_24h",
    "coord_active_deployments",
    "bootstrap_enabled",
    "federate_id",
    "coord_redis_configured",
)


def _parse_federation_block(fed_raw: Any) -> dict[str, Any] | None:
    if not isinstance(fed_raw, dict):
        return None
    out: dict[str, Any] = {}
    for key in _FEDERATION_KEYS:
        if key not in fed_raw:
            continue
        val = fed_raw[key]
        if key == "federate_id":
            out[key] = str(val) if val is not None else None
        elif key in ("bootstrap_enabled", "coord_redis_configured"):
            out[key] = bool(val)
        elif key == "coord_active_deployments":
            out[key] = int(val) if val is not None else None
        else:
            out[key] = int(val)
    return out or None


def _parse_corpus_block(corpus_raw: Any) -> dict[str, int] | None:
    if not isinstance(corpus_raw, dict):
        return None
    corpus_out: dict[str, int] = {}
    for key in _CORPUS_KEYS:
        if key in corpus_raw:
            corpus_out[key] = int(corpus_raw[key])
    return corpus_out or None


def _parse_stats_body(body: Any, stats_url: str) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("stats response is not a JSON object")

    deployments_raw = body.get("deployments") if isinstance(body.get("deployments"), dict) else body
    if not isinstance(deployments_raw, dict):
        raise ValueError("stats response missing deployments block")

    missing = [k for k in _REQUIRED_KEYS if k not in deployments_raw]
    if missing:
        raise ValueError(f"stats response missing fields: {', '.join(missing)}")

    out: dict[str, Any] = {
        "deployments_total": int(deployments_raw["deployments_total"]),
        "deployments_online": int(deployments_raw["deployments_online"]),
        "bots_online_sum": int(deployments_raw["bots_online_sum"]),
        "stats_url": stats_url,
    }
    ttl = body.get("online_ttl_sec", deployments_raw.get("online_ttl_sec"))
    if ttl is not None:
        out["online_ttl_sec"] = int(ttl)
    as_of = body.get("as_of")
    if isinstance(as_of, str):
        out["as_of"] = as_of
    for key in ("deployments_online_sharded", "shard_workers_online_sum"):
        if key in deployments_raw:
            out[key] = int(deployments_raw[key])
    for key in _DEPLOYMENT_EXTRA_KEYS:
        if key in deployments_raw:
            out[key] = int(deployments_raw[key])
    versions = deployments_raw.get("online_versions")
    if isinstance(versions, list):
        out["online_versions"] = [
            {"version": str(item["version"]), "count": int(item["count"])}
            for item in versions
            if isinstance(item, dict) and "version" in item and "count" in item
        ]
    corpus_raw = body.get("corpus")
    corpus_out = _parse_corpus_block(corpus_raw)
    if corpus_out:
        out["corpus"] = corpus_out
    if "corpus_enabled" in body:
        out["corpus_enabled"] = bool(body["corpus_enabled"])
    federation_out = _parse_federation_block(body.get("federation"))
    if federation_out:
        out["federation"] = federation_out
    return out


async def _fetch_from_urls(urls: list[str], *, timeout_sec: float) -> dict[str, Any]:
    scrub_http_log_noise()
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        for stats_url in urls:
            try:
                resp = await client.get(stats_url)
                resp.raise_for_status()
                return _parse_stats_body(resp.json(), stats_url)
            except (httpx.HTTPError, ValueError) as e:
                last_err = e
                logger.debug("community_stats: fetch stats failed url={}: {}", stats_url, e)
    if last_err is not None:
        raise last_err
    raise ValueError("community stats fetch failed")


async def fetch_community_public_stats() -> dict[str, Any]:
    cfg = get_community_stats_config()
    monitor_urls = monitor_overview_urls_for_config(cfg)
    stats_urls = stats_urls_for_config(cfg)
    if not monitor_urls and not stats_urls:
        raise ValueError("no community stats URL configured")

    monitor_task: asyncio.Task[dict[str, Any]] | None = None
    stats_task: asyncio.Task[dict[str, Any]] | None = None
    if monitor_urls:
        monitor_task = asyncio.create_task(
            _fetch_from_urls(monitor_urls, timeout_sec=_MONITOR_TIMEOUT_SEC),
        )
    if stats_urls:
        stats_task = asyncio.create_task(
            _fetch_from_urls(stats_urls, timeout_sec=_STATS_TIMEOUT_SEC),
        )

    data: dict[str, Any] | None = None
    monitor_err: Exception | None = None
    if monitor_task is not None:
        try:
            data = await monitor_task
            if stats_task is not None and not stats_task.done():
                stats_task.cancel()
        except Exception as e:
            monitor_err = e
            logger.debug("community_stats: monitor overview unavailable, fallback to /v1/stats: {}", e)

    if data is None:
        if stats_task is None:
            raise monitor_err or ValueError("community stats fetch failed")
        try:
            data = await stats_task
        except Exception as stats_err:
            if monitor_err is not None:
                raise stats_err from monitor_err
            raise

    logger.debug(
        "community stats fetched: total={} online={} bots_sum={} url={}",
        data["deployments_total"],
        data["deployments_online"],
        data["bots_online_sum"],
        data.get("stats_url"),
    )
    return data


async def fetch_community_corpus_hot(
    *,
    mode: str = "pool",
    period: str = "day",
    limit: int = 40,
) -> dict[str, Any]:
    from src.features.community_stats.endpoints import corpus_hot_urls_for_config

    cfg = get_community_stats_config()
    urls = corpus_hot_urls_for_config(cfg)
    if not urls:
        raise ValueError("no community stats URL configured")
    mode_norm = mode if mode in {"pool", "recent", "fleet"} else "pool"
    period_norm = period if period in {"day", "week", "month"} else "day"
    limit_norm = max(5, min(int(limit), 80))
    scrub_http_log_noise()
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=_STATS_TIMEOUT_SEC) as client:
        for base_url in urls:
            url = f"{base_url}?mode={mode_norm}&period={period_norm}&limit={limit_norm}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                body = resp.json()
                if not isinstance(body, dict):
                    raise ValueError("corpus hot response is not a JSON object")
                return body
            except (httpx.HTTPError, ValueError) as e:
                last_err = e
                logger.debug("community_stats: fetch corpus hot failed url={}: {}", url, e)
    if last_err is not None:
        raise last_err
    raise ValueError("community corpus hot fetch failed")
