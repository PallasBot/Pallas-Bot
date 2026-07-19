from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import httpx
from nonebot import logger

from pallas.core.shared.ai_runtime_failure import (
    FAILURE_CONNECTION_FAILED,
    FAILURE_TIMEOUT,
    FAILURE_UNKNOWN,
    FAILURE_UPSTREAM_HTTP_ERROR,
    HEALTH_HEALTHY,
    HEALTH_UNHEALTHY,
    failure_class_from_error,
)

from .runtime import enrich_probe_result_capability
from .types import ServiceProbeResult

if TYPE_CHECKING:
    from pallas.core.shared.ai_runtime_capability import AiRuntimeCapability


def clamp_timeout_sec(timeout_sec: float, *, floor: float = 5.0, cap: float = 30.0) -> float:
    return min(cap, max(floor, timeout_sec))


async def probe_http_get(
    client: httpx.AsyncClient,
    *,
    category: str,
    site: str,
    url: str,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 15.0,
    capability: AiRuntimeCapability | None = None,
) -> ServiceProbeResult:
    timeout = clamp_timeout_sec(timeout_sec)
    started = time.perf_counter()
    try:
        r = await client.get(
            url,
            headers=headers or {},
            timeout=httpx.Timeout(timeout, connect=min(15.0, timeout)),
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        ok = 200 <= r.status_code < 300
        return enrich_probe_result_capability(
            ServiceProbeResult(
                category=category,
                site=site,
                ok=ok,
                latency_ms=elapsed_ms,
                status_code=r.status_code,
                error=None if ok else None,
                health_state=HEALTH_HEALTHY if ok else HEALTH_UNHEALTHY,
                failure_class=None if ok else FAILURE_UPSTREAM_HTTP_ERROR,
            ),
            capability,
        )
    except httpx.TimeoutException:
        return enrich_probe_result_capability(
            ServiceProbeResult(
                category,
                site,
                False,
                None,
                None,
                "超时",
                health_state=HEALTH_UNHEALTHY,
                failure_class=FAILURE_TIMEOUT,
            ),
            capability,
        )
    except httpx.ConnectError:
        return enrich_probe_result_capability(
            ServiceProbeResult(
                category,
                site,
                False,
                None,
                None,
                "连接失败",
                health_state=HEALTH_UNHEALTHY,
                failure_class=FAILURE_CONNECTION_FAILED,
            ),
            capability,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("service_probe GET {} {}: {}", category, site, e)
        message = str(e)[:120]
        return enrich_probe_result_capability(
            ServiceProbeResult(
                category,
                site,
                False,
                None,
                None,
                message,
                health_state=HEALTH_UNHEALTHY,
                failure_class=failure_class_from_error(message) or FAILURE_UNKNOWN,
            ),
            capability,
        )


async def probe_http_post_json(
    client: httpx.AsyncClient,
    *,
    category: str,
    site: str,
    url: str,
    json_body: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_sec: float = 15.0,
    capability: AiRuntimeCapability | None = None,
) -> ServiceProbeResult:
    timeout = clamp_timeout_sec(timeout_sec)
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    started = time.perf_counter()
    try:
        r = await client.post(
            url,
            json=json_body,
            headers=hdrs,
            timeout=httpx.Timeout(timeout, connect=min(15.0, timeout)),
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        ok = 200 <= r.status_code < 300
        return enrich_probe_result_capability(
            ServiceProbeResult(
                category=category,
                site=site,
                ok=ok,
                latency_ms=elapsed_ms,
                status_code=r.status_code,
                error=None,
                health_state=HEALTH_HEALTHY if ok else HEALTH_UNHEALTHY,
                failure_class=None if ok else FAILURE_UPSTREAM_HTTP_ERROR,
            ),
            capability,
        )
    except httpx.TimeoutException:
        return enrich_probe_result_capability(
            ServiceProbeResult(
                category,
                site,
                False,
                None,
                None,
                "超时",
                health_state=HEALTH_UNHEALTHY,
                failure_class=FAILURE_TIMEOUT,
            ),
            capability,
        )
    except httpx.ConnectError:
        return enrich_probe_result_capability(
            ServiceProbeResult(
                category,
                site,
                False,
                None,
                None,
                "连接失败",
                health_state=HEALTH_UNHEALTHY,
                failure_class=FAILURE_CONNECTION_FAILED,
            ),
            capability,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("service_probe POST {} {}: {}", category, site, e)
        message = str(e)[:120]
        return enrich_probe_result_capability(
            ServiceProbeResult(
                category,
                site,
                False,
                None,
                None,
                message,
                health_state=HEALTH_UNHEALTHY,
                failure_class=failure_class_from_error(message) or FAILURE_UNKNOWN,
            ),
            capability,
        )
