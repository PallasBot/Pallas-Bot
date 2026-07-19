"""拉取中心 GET /v1/federation/onboarding。"""

from __future__ import annotations

from typing import Any

import httpx
from nonebot import logger

from pallas.product.community_stats.config import get_community_stats_config
from pallas.product.community_stats.endpoints import heartbeat_urls_for_config, normalize_heartbeat_url
from pallas.product.message_scrub.quiet_http_loggers import scrub_http_log_noise

_HTTP_TIMEOUT_SEC = 12.0
_DEFAULT_ONBOARDING = "https://stats.pallasbot.top/v1/federation/onboarding"


def federation_onboarding_url_from_endpoint(heartbeat_endpoint: str) -> str:
    url = normalize_heartbeat_url(heartbeat_endpoint)
    if not url:
        return _DEFAULT_ONBOARDING
    if url.endswith("/heartbeat"):
        return f"{url[: -len('/heartbeat')]}/federation/onboarding"
    if url.endswith("/v1/federation/onboarding"):
        return url
    return f"{url}/federation/onboarding"


def federation_onboarding_urls_for_config(cfg=None) -> list[str]:
    cfg = cfg or get_community_stats_config()
    from pallas.product.community_stats.endpoints import custom_heartbeat_url

    custom = custom_heartbeat_url(cfg)
    if custom:
        return [federation_onboarding_url_from_endpoint(custom)]
    return [federation_onboarding_url_from_endpoint(u) for u in heartbeat_urls_for_config(cfg)]


async def fetch_federation_onboarding() -> dict[str, Any]:
    urls = federation_onboarding_urls_for_config()
    if not urls:
        raise ValueError("no federation onboarding URL configured")
    scrub_http_log_noise()
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                if resp.status_code == 503:
                    raise ValueError("federation onboarding disabled on center")
                resp.raise_for_status()
                body = resp.json()
                if not isinstance(body, dict):
                    raise ValueError("onboarding response is not a JSON object")
                body["onboarding_url"] = url
                return body
            except (httpx.HTTPError, ValueError) as e:
                last_err = e
                logger.debug("federation_onboarding: fetch failed url={}: {}", url, e)
    if last_err is not None:
        raise last_err
    raise ValueError("federation onboarding fetch failed")
