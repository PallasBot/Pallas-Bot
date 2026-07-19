"""并行运行已注册的服务网关探测 provider。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.console.webui.gateway_fields import ALL_GATEWAY_FIELDS
from pallas.product.service_gateways import llm_probe as _llm_probe  # noqa: F401
from pallas.product.service_gateways import media_probe as _media_probe  # noqa: F401
from pallas.product.service_gateways.registry import run_service_probes

if TYPE_CHECKING:
    from pallas.core.shared.service_probe import ServiceProbeResult


async def probe_all_connectivity(*, timeout_sec: float = 15.0) -> list[ServiceProbeResult]:
    return await run_service_probes(timeout_sec=timeout_sec)


async def probe_all_connectivity_from_draft(
    values: dict[str, Any] | None = None,
    *,
    timeout_sec: float = 15.0,
) -> list[ServiceProbeResult]:
    raw = values or {}
    if not raw:
        return await probe_all_connectivity(timeout_sec=timeout_sec)
    unknown = set(raw.keys()) - ALL_GATEWAY_FIELDS
    if unknown:
        raise ValueError(f"未知配置项: {', '.join(sorted(unknown))}")
    return await run_service_probes(timeout_sec=timeout_sec, draft_values=dict(raw))
