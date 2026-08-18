"""GET /v1/bootstrap：拉取并落盘 federate_id 与协调 Redis。"""

from __future__ import annotations

import time

import httpx
from nonebot import logger

from pallas.product.community_stats.config import get_community_stats_config
from pallas.product.community_stats.endpoints import heartbeat_urls_for_config, normalize_heartbeat_url
from pallas.product.community_stats.store import load_or_create_deployment_id
from pallas.product.control_plane.config import (
    INSTANCE_SECRET_ENV_KEY,
    ControlPlaneConfig,
    clear_control_plane_config_cache,
    control_plane_wanted,
    get_control_plane_config,
    should_run_bootstrap_refresh,
)
from pallas.product.control_plane.store import bootstrap_state_valid, save_bootstrap_payload
from pallas.product.message_scrub.quiet_http_loggers import scrub_http_log_noise

_HTTP_TIMEOUT_SEC = 15.0


def bootstrap_url_from_heartbeat(heartbeat_url: str) -> str:
    url = normalize_heartbeat_url(heartbeat_url)
    if url.endswith("/heartbeat"):
        return f"{url[: -len('/heartbeat')]}/bootstrap"
    return f"{url}/bootstrap"


def bootstrap_urls(cfg: ControlPlaneConfig | None = None) -> list[str]:
    cfg = cfg or get_control_plane_config()
    manual = (cfg.bootstrap_url or "").strip().rstrip("/")
    if manual:
        return [manual]
    cs_cfg = get_community_stats_config()
    return [bootstrap_url_from_heartbeat(u) for u in heartbeat_urls_for_config(cs_cfg)]


def bootstrap_headers(cfg: ControlPlaneConfig | None = None) -> dict[str, str]:
    cfg = cfg or get_control_plane_config()
    headers = {
        "Content-Type": "application/json",
        "X-Deployment-Id": load_or_create_deployment_id(),
    }
    secret = (cfg.instance_secret or "").strip()
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    token = (get_community_stats_config().token or "").strip()
    if not secret and token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def clear_bootstrap_runtime_caches() -> None:
    from pallas.core.platform.federate.config import clear_federate_config_cache

    clear_federate_config_cache()


async def maybe_autofill_instance_secret_from_onboarding() -> bool:
    """控制面已开且未填入池密钥时，从公开 onboarding 写入密钥（社区池口令，非私密）。"""
    cfg = get_control_plane_config()
    if not control_plane_wanted(cfg):
        return False
    if (cfg.instance_secret or "").strip():
        return False
    try:
        from pallas.product.community_stats.federation_onboarding import fetch_federation_onboarding

        body = await fetch_federation_onboarding()
    except Exception as e:
        logger.debug("control_plane autofill secret: onboarding failed: {}", e)
        return False
    secret = str((body or {}).get("instance_secret") or "").strip()
    if not secret:
        return False
    try:
        from pallas.core.foundation.config.repo_settings import upsert_repo_settings_items

        upsert_repo_settings_items({INSTANCE_SECRET_ENV_KEY: secret})
    except Exception as e:
        logger.warning("control_plane autofill secret: persist failed: {}", e)
        return False
    clear_control_plane_config_cache()
    clear_bootstrap_runtime_caches()
    logger.info("control_plane autofill secret: wrote instance secret from community onboarding")
    return True


async def refresh_control_plane_bootstrap(*, force: bool = False) -> bool:
    """拉取 bootstrap 并落盘；成功返回 True。"""
    await maybe_autofill_instance_secret_from_onboarding()
    if not should_run_bootstrap_refresh() and not force:
        return bootstrap_state_valid()

    cfg = get_control_plane_config()
    if not (cfg.instance_secret or "").strip() and not (get_community_stats_config().token or "").strip():
        logger.warning("control_plane bootstrap: no instance secret (autofill unavailable)")
        return bootstrap_state_valid()

    urls = bootstrap_urls(cfg)
    if not urls:
        logger.warning("control_plane bootstrap: no URL configured")
        return bootstrap_state_valid()

    headers = bootstrap_headers(cfg)
    last_error = ""
    try:
        async with scrub_http_log_noise():
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
                for endpoint in urls:
                    try:
                        resp = await client.get(endpoint, headers=headers)
                    except httpx.HTTPError as e:
                        last_error = type(e).__name__
                        logger.warning("Control-plane bootstrap failed with error type [{}]", type(e).__name__)
                        continue
                    if resp.status_code != 200:
                        last_error = f"HTTP {resp.status_code}"
                        logger.warning(
                            "Control-plane bootstrap returned HTTP [{}] from endpoint [{}]",
                            resp.status_code,
                            endpoint,
                        )
                        continue
                    data = resp.json()
                    if not isinstance(data, dict):
                        last_error = "invalid json body"
                        continue
                    federate_id = str(data.get("federate_id") or "").strip()
                    coord_raw = data.get("coord")
                    coord: dict[str, object] | None = None
                    if isinstance(coord_raw, dict):
                        redis_url = str(coord_raw.get("redis_url") or "").strip()
                        if redis_url:
                            coord = {
                                "redis_url": redis_url,
                                "redis_prefix": str(coord_raw.get("redis_prefix") or "").strip(),
                                "claim_ttl_sec": coord_raw.get("claim_ttl_sec"),
                            }
                    corpus_raw = data.get("corpus_community")
                    corpus_community: dict[str, object] | None = None
                    if isinstance(corpus_raw, dict):
                        api_base = str(corpus_raw.get("api_base") or "").strip().rstrip("/")
                        if api_base:
                            corpus_community = {
                                "api_base": api_base,
                                "readable": bool(corpus_raw.get("readable")),
                                "writable": bool(corpus_raw.get("writable")),
                            }
                    expires_raw = data.get("expires_at")
                    expires_at = int(expires_raw) if expires_raw is not None else int(time.time()) + 86400
                    save_bootstrap_payload(
                        federate_id=federate_id,
                        coord=coord,
                        corpus_community=corpus_community,
                        expires_at=expires_at,
                    )
                    clear_bootstrap_runtime_caches()
                    logger.info(
                        "Control-plane bootstrap succeeded for federate ID [{}] with Redis [{}]",
                        federate_id or "-",
                        bool(coord and coord.get("redis_url")),
                    )
                    return True
    except Exception as e:
        last_error = type(e).__name__
        logger.warning("Control-plane bootstrap failed with error type [{}]", type(e).__name__)

    if last_error:
        logger.debug("Control-plane bootstrap exhausted all endpoints with error [{}]", last_error)
    return bootstrap_state_valid()


async def ensure_control_plane_bootstrap(*, force: bool = False) -> bool:
    await maybe_autofill_instance_secret_from_onboarding()
    if not force and bootstrap_state_valid():
        return True
    return await refresh_control_plane_bootstrap(force=force)
