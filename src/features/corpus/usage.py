"""拉取中心 GET /v1/corpus/usage。"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
from nonebot import logger

from src.features.corpus.config import (
    community_configured,
    resolved_community_api_base_urls,
    resolved_community_token,
)
from src.features.corpus.store import corpus_community_enrollment_valid
from src.features.message_scrub.quiet_http_loggers import scrub_http_log_noise

_HTTP_TIMEOUT_SEC = float(os.getenv("PALLAS_CORPUS_USAGE_HTTP_TIMEOUT_SEC", "3"))
_USAGE_CACHE_TTL_SEC = float(os.getenv("PALLAS_CORPUS_USAGE_CACHE_SEC", "120"))
_usage_cache: tuple[float, dict[str, Any] | None] | None = None
_usage_lock = asyncio.Lock()
_usage_inflight: asyncio.Task[dict[str, Any] | None] | None = None


async def fetch_corpus_community_usage() -> dict[str, Any] | None:
    global _usage_inflight
    now = time.monotonic()
    cached = _usage_cache
    if cached is not None and now < cached[0]:
        return cached[1]

    async with _usage_lock:
        cached = _usage_cache
        if cached is not None and now < cached[0]:
            return cached[1]
        inflight = _usage_inflight
        if inflight is not None and not inflight.done():
            task = inflight
        else:
            task = asyncio.create_task(_fetch_corpus_community_usage_uncached())
            _usage_inflight = task

    try:
        return await task
    finally:
        async with _usage_lock:
            if _usage_inflight is task:
                _usage_inflight = None


async def invalidate_corpus_usage_cache() -> None:
    global _usage_cache, _usage_inflight
    async with _usage_lock:
        _usage_cache = None
        inflight = _usage_inflight
        _usage_inflight = None
    if inflight is not None and not inflight.done():
        inflight.cancel()


def remember_corpus_usage_cache(result: dict[str, Any] | None) -> dict[str, Any] | None:
    global _usage_cache
    expire = time.monotonic() + max(5.0, _USAGE_CACHE_TTL_SEC)
    _usage_cache = (expire, result)
    return result


async def _fetch_corpus_community_usage_uncached() -> dict[str, Any] | None:
    if not corpus_community_enrollment_valid() and not community_configured():
        return None
    token = resolved_community_token()
    bases = resolved_community_api_base_urls()
    if not token or not bases:
        return None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    last_error = ""
    try:
        async with scrub_http_log_noise():
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
                for base in bases:
                    usage_url = f"{base.rstrip('/')}/usage"
                    if not usage_url.startswith("http"):
                        continue
                    try:
                        resp = await client.get(usage_url, headers=headers)
                    except httpx.HTTPError as e:
                        last_error = str(e)
                        logger.debug("corpus usage fetch failed api_base={}: {}", base, e)
                        continue
                    if resp.status_code == 401:
                        from src.features.corpus.enroll import maybe_refresh_corpus_enrollment_on_auth_failure

                        await maybe_refresh_corpus_enrollment_on_auth_failure()
                        async with _usage_lock:
                            return remember_corpus_usage_cache(None)
                    if resp.status_code != 200:
                        last_error = f"HTTP {resp.status_code}"
                        continue
                    data = resp.json()
                    if not isinstance(data, dict):
                        continue
                    result = {
                        "read_lookups": int(data.get("read_lookups") or 0),
                        "read_hits": int(data.get("read_hits") or 0),
                        "contribute_ok": int(data.get("contribute_ok") or 0),
                        "updated_at": int(data["updated_at"]) if data.get("updated_at") is not None else None,
                        "source": "community_stats",
                    }
                    async with _usage_lock:
                        return remember_corpus_usage_cache(result)
    except httpx.HTTPError as e:
        last_error = str(e)
        logger.debug("corpus usage fetch failed: {}", e)
    if last_error:
        logger.debug("corpus usage: no endpoint succeeded last_error={}", last_error)
    async with _usage_lock:
        return remember_corpus_usage_cache(None)
