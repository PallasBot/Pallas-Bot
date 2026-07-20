"""社区中心连通探测：HTTPS 探活 + 上报状态诊断包。"""

from __future__ import annotations

import time
from typing import Any

import httpx
from nonebot import logger

from pallas.product.community_stats.config import get_community_stats_config
from pallas.product.community_stats.endpoints import (
    FALLBACK_HEARTBEAT,
    PRIMARY_HEARTBEAT,
    custom_heartbeat_url,
)
from pallas.product.community_stats.stats_url import stats_url_from_endpoint
from pallas.product.community_stats.store import load_community_stats_state, load_or_create_deployment_id
from pallas.product.message_scrub.quiet_http_loggers import scrub_http_log_noise

_PROBE_TIMEOUT_SEC = 8.0


def connectivity_probe_urls() -> list[str]:
    """自动模式固定主+备；自定义 endpoint 只测一条。"""
    cfg = get_community_stats_config()
    custom = custom_heartbeat_url(cfg)
    if custom:
        return [stats_url_from_endpoint(custom)]
    return [
        stats_url_from_endpoint(PRIMARY_HEARTBEAT),
        stats_url_from_endpoint(FALLBACK_HEARTBEAT),
    ]


def _error_text(exc: BaseException) -> str:
    name = type(exc).__name__
    msg = str(exc).strip()
    if not msg:
        return name
    return f"{name}: {msg[:160]}"


async def _probe_one(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        resp = await client.get(url)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code >= 200 and resp.status_code < 300:
            try:
                body = resp.json()
            except ValueError:
                return {
                    "url": url,
                    "ok": False,
                    "latency_ms": latency_ms,
                    "http_status": resp.status_code,
                    "error": "响应不是合法 JSON",
                }
            if not isinstance(body, dict):
                return {
                    "url": url,
                    "ok": False,
                    "latency_ms": latency_ms,
                    "http_status": resp.status_code,
                    "error": "响应不是 JSON 对象",
                }
            return {
                "url": url,
                "ok": True,
                "latency_ms": latency_ms,
                "http_status": resp.status_code,
                "error": None,
            }
        return {
            "url": url,
            "ok": False,
            "latency_ms": latency_ms,
            "http_status": resp.status_code,
            "error": f"HTTP {resp.status_code}",
        }
    except httpx.HTTPError as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "url": url,
            "ok": False,
            "latency_ms": latency_ms,
            "http_status": None,
            "error": _error_text(e),
        }


def _build_hint(*, any_ok: bool, enabled: bool, probes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    if not probes:
        parts.append("未配置探测地址")
    elif any_ok:
        ok_n = sum(1 for p in probes if p.get("ok"))
        if ok_n == len(probes):
            parts.append("社区中心可达")
        else:
            parts.append("部分入口可达")
    else:
        parts.append("社区中心不可达")
    parts.append("上报已开启" if enabled else "上报已关闭")
    return "；".join(parts)


async def probe_community_connectivity() -> dict[str, Any]:
    cfg = get_community_stats_config()
    urls = connectivity_probe_urls()
    probes: list[dict[str, Any]] = []
    scrub_http_log_noise()
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SEC) as client:
        for url in urls:
            result = await _probe_one(client, url)
            probes.append(result)
            if not result["ok"]:
                logger.debug(
                    "community_stats: connectivity probe failed url={} err={}",
                    url,
                    result.get("error"),
                )

    state = load_community_stats_state()
    active = str(state.get("heartbeat_endpoint") or "").strip() or None
    last_ok = state.get("last_heartbeat_ok_unix")
    last_probe = state.get("last_primary_probe_unix")
    try:
        deployment_id = load_or_create_deployment_id()
    except OSError as e:
        logger.warning(
            "community_stats: load_or_create_deployment_id failed, fallback to state: {}",
            e,
        )
        deployment_id = str(state.get("deployment_id") or "").strip() or None

    any_ok = any(bool(p.get("ok")) for p in probes)
    reporting = {
        "enabled": bool(cfg.enabled),
        "endpoint": (cfg.endpoint or "").strip() or PRIMARY_HEARTBEAT,
        "active_heartbeat_endpoint": active,
        "deployment_id": deployment_id,
        "last_heartbeat_ok_unix": int(last_ok) if last_ok is not None else None,
        "last_primary_probe_unix": int(last_probe) if last_probe is not None else None,
    }
    return {
        "probes": probes,
        "reporting": reporting,
        "summary": {
            "any_ok": any_ok,
            "hint": _build_hint(any_ok=any_ok, enabled=bool(cfg.enabled), probes=probes),
        },
    }
