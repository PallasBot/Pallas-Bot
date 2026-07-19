from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.shared.ai_runtime_failure import (
    CIRCUIT_CLOSED,
    CIRCUIT_UNKNOWN,
    FAILURE_RUNTIME_DEGRADED,
    FAILURE_RUNTIME_DISABLED,
    HEALTH_DEGRADED,
    HEALTH_HEALTHY,
    HEALTH_UNKNOWN,
    RUNTIME_DEGRADED,
    RUNTIME_DISABLED,
    RUNTIME_HEALTHY,
    failure_class_from_error,
)

from .types import ServiceProbeResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from pallas.core.shared.ai_runtime_capability import AiRuntimeCapability


def enrich_probe_result_capability(
    result: ServiceProbeResult,
    capability: AiRuntimeCapability | None,
) -> ServiceProbeResult:
    if capability is None:
        return result
    return ServiceProbeResult(
        category=result.category,
        site=result.site,
        ok=result.ok,
        latency_ms=result.latency_ms,
        status_code=result.status_code,
        error=result.error,
        runtime_state=result.runtime_state,
        runtime_detail=result.runtime_detail,
        capability_id=result.capability_id or capability.capability_id,
        capability_group=result.capability_group or capability.capability_group,
        runtime_type=result.runtime_type or capability.runtime_type,
        failure_class=result.failure_class,
        health_state=result.health_state,
        circuit_state=result.circuit_state,
        consecutive_failures=result.consecutive_failures,
        recent_failure_class=result.recent_failure_class,
        queue_load_hint=result.queue_load_hint,
    )


def enrich_probe_result_capabilities(
    results: list[ServiceProbeResult],
    capability: AiRuntimeCapability | None,
) -> list[ServiceProbeResult]:
    return [enrich_probe_result_capability(item, capability) for item in results]


def patch_probe_result(result: ServiceProbeResult, **changes) -> ServiceProbeResult:
    data = result.to_dict()
    data.update(changes)
    return ServiceProbeResult(**data)


def build_runtime_probe_result(
    capability: AiRuntimeCapability | None,
    *,
    category: str,
    site: str,
    ok: bool,
    latency_ms: int | float | None,
    status_code: int | None,
    error: str | None,
    runtime_state=None,
    runtime_detail: str | None = None,
    failure_class=None,
    health_state=None,
    circuit_state=None,
    consecutive_failures: int | None = None,
    recent_failure_class=None,
    queue_load_hint: str | None = None,
    disabled_when: Callable[[ServiceProbeResult], bool] | None = None,
    disabled_health_state=HEALTH_UNKNOWN,
) -> ServiceProbeResult:
    return normalize_runtime_probe_result(
        enrich_probe_result_capability(
            ServiceProbeResult(
                category=category,
                site=site,
                ok=ok,
                latency_ms=int(round(latency_ms)) if isinstance(latency_ms, float) else latency_ms,
                status_code=status_code,
                error=error,
                runtime_state=runtime_state,
                runtime_detail=runtime_detail,
                failure_class=failure_class,
                health_state=health_state,
                circuit_state=circuit_state,
                consecutive_failures=consecutive_failures,
                recent_failure_class=recent_failure_class,
                queue_load_hint=queue_load_hint,
            ),
            capability,
        ),
        disabled_when=disabled_when,
        disabled_health_state=disabled_health_state,
    )


def normalize_runtime_probe_result(
    result: ServiceProbeResult,
    *,
    disabled_when: Callable[[ServiceProbeResult], bool] | None = None,
    disabled_health_state=HEALTH_UNKNOWN,
) -> ServiceProbeResult:
    runtime_state = result.runtime_state
    if runtime_state is None:
        if disabled_when and disabled_when(result):
            runtime_state = RUNTIME_DISABLED
        elif result.ok:
            runtime_state = RUNTIME_HEALTHY
        else:
            runtime_state = RUNTIME_DEGRADED

    runtime_detail = result.runtime_detail
    if runtime_detail is None and result.error:
        runtime_detail = result.error

    failure_class = result.failure_class or failure_class_from_error(result.error)
    health_state = result.health_state
    if health_state is None:
        if runtime_state == RUNTIME_HEALTHY:
            health_state = HEALTH_HEALTHY
        elif runtime_state == RUNTIME_DISABLED:
            health_state = disabled_health_state
        else:
            health_state = HEALTH_DEGRADED

    return ServiceProbeResult(
        category=result.category,
        site=result.site,
        ok=result.ok,
        latency_ms=result.latency_ms,
        status_code=result.status_code,
        error=result.error,
        runtime_state=runtime_state,
        runtime_detail=runtime_detail,
        capability_id=result.capability_id,
        capability_group=result.capability_group,
        runtime_type=result.runtime_type,
        failure_class=failure_class,
        health_state=health_state,
        circuit_state=result.circuit_state,
        consecutive_failures=result.consecutive_failures,
        recent_failure_class=result.recent_failure_class,
        queue_load_hint=result.queue_load_hint,
    )


def normalize_runtime_probe_results(
    results: list[ServiceProbeResult],
    *,
    disabled_when: Callable[[ServiceProbeResult], bool] | None = None,
    disabled_health_state=HEALTH_UNKNOWN,
) -> list[ServiceProbeResult]:
    return [
        normalize_runtime_probe_result(
            item,
            disabled_when=disabled_when,
            disabled_health_state=disabled_health_state,
        )
        for item in results
    ]


def runtime_result_from_circuit_state(
    *,
    category: str,
    site: str,
    capability_id: str | None = None,
    capability_group: str | None = None,
    runtime_type: str | None = None,
    disabled_message: str | None = None,
    degraded_message: str | None = None,
    healthy_message: str | None = None,
    circuit_state=CIRCUIT_CLOSED,
    consecutive_failures: int = 0,
    recent_failure_reason: str | None = None,
    capability: AiRuntimeCapability | None = None,
) -> ServiceProbeResult:
    if capability is not None:
        capability_id = capability_id or capability.capability_id
        capability_group = capability_group or capability.capability_group
        runtime_type = runtime_type or capability.runtime_type
    if disabled_message is not None:
        return ServiceProbeResult(
            category=category,
            site=site,
            ok=False,
            latency_ms=None,
            status_code=None,
            error=disabled_message,
            runtime_state=RUNTIME_DISABLED,
            runtime_detail=disabled_message,
            capability_id=capability_id,
            capability_group=capability_group,
            runtime_type=runtime_type,
            failure_class=FAILURE_RUNTIME_DISABLED,
            health_state=HEALTH_UNKNOWN,
            circuit_state=CIRCUIT_UNKNOWN,
            consecutive_failures=0,
        )
    if degraded_message is not None:
        return ServiceProbeResult(
            category=category,
            site=site,
            ok=False,
            latency_ms=None,
            status_code=None,
            error=degraded_message,
            runtime_state=RUNTIME_DEGRADED,
            runtime_detail=degraded_message,
            capability_id=capability_id,
            capability_group=capability_group,
            runtime_type=runtime_type,
            failure_class=FAILURE_RUNTIME_DEGRADED,
            health_state=HEALTH_DEGRADED,
            circuit_state=circuit_state,
            consecutive_failures=consecutive_failures,
            recent_failure_class=failure_class_from_error(recent_failure_reason),
        )
    return ServiceProbeResult(
        category=category,
        site=site,
        ok=True,
        latency_ms=None,
        status_code=None,
        error=healthy_message,
        runtime_state=RUNTIME_HEALTHY,
        runtime_detail=healthy_message,
        capability_id=capability_id,
        capability_group=capability_group,
        runtime_type=runtime_type,
        health_state=HEALTH_HEALTHY,
        circuit_state=circuit_state,
        consecutive_failures=consecutive_failures,
    )
