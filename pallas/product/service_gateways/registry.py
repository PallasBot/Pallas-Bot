"""服务网关探测 provider 注册表。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pallas.core.shared.service_probe import ServiceProbeResult

ProbeFn = Callable[..., Awaitable[list[ServiceProbeResult]]]

_providers: dict[str, ServiceProbeProvider] = {}


@dataclass(frozen=True, slots=True)
class ServiceProbeProvider:
    name: str
    probe: ProbeFn
    priority: int = 50


def register_service_probe_provider(provider: ServiceProbeProvider) -> None:
    _providers[provider.name] = provider


def registered_service_probe_names() -> frozenset[str]:
    return frozenset(_providers.keys())


async def run_service_probes(
    *,
    timeout_sec: float = 15.0,
    draft_values: dict[str, Any] | None = None,
) -> list[ServiceProbeResult]:
    ordered = sorted(_providers.values(), key=lambda item: (item.priority, item.name))
    if not ordered:
        return []

    kwargs: dict[str, Any] = {"timeout_sec": timeout_sec}
    if draft_values is not None:
        kwargs["draft_values"] = draft_values

    tasks = [provider.probe(**kwargs) for provider in ordered]
    chunks = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[ServiceProbeResult] = []
    for provider, chunk in zip(ordered, chunks, strict=True):
        if isinstance(chunk, BaseException):
            results.append(
                ServiceProbeResult(
                    category=provider.name,
                    site="探测",
                    ok=False,
                    latency_ms=None,
                    status_code=None,
                    error=str(chunk)[:120],
                ),
            )
            continue
        results.extend(chunk)
    return results
