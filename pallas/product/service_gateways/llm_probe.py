"""智能对话服务探测。"""

from __future__ import annotations

import time

from pallas.core.shared.ai_runtime_capability import LLM_CHAT
from pallas.core.shared.ai_runtime_failure import (
    FAILURE_RUNTIME_DEGRADED,
    FAILURE_RUNTIME_DISABLED,
    FAILURE_RUNTIME_UNAVAILABLE,
    FAILURE_UPSTREAM_HTTP_ERROR,
    HEALTH_UNKNOWN,
    RUNTIME_DISABLED,
    failure_class_from_error,
)
from pallas.core.shared.service_probe import (
    ServiceProbeResult,
    build_runtime_probe_result,
)
from pallas.product.service_gateways.registry import ServiceProbeProvider, register_service_probe_provider

LLM_CATEGORY = "LLM对话"
LLM_SITE = "健康检查"


def llm_runtime_result(
    *,
    ok: bool,
    latency_ms: float | None,
    status_code: int | None,
    error: str | None,
    runtime_state=None,
    runtime_detail: str | None = None,
    failure_class=None,
    disabled_health_state=HEALTH_UNKNOWN,
    health_state=None,
    circuit_state=None,
    recent_failure_class=None,
) -> ServiceProbeResult:
    return build_runtime_probe_result(
        LLM_CHAT,
        category=LLM_CATEGORY,
        site=LLM_SITE,
        ok=ok,
        latency_ms=latency_ms,
        status_code=status_code,
        error=error,
        runtime_state=runtime_state,
        runtime_detail=runtime_detail,
        failure_class=failure_class,
        disabled_health_state=disabled_health_state,
        health_state=health_state,
        circuit_state=circuit_state,
        recent_failure_class=recent_failure_class,
    )


async def probe_llm_service(*, timeout_sec: float = 15.0, draft_values=None) -> list[ServiceProbeResult]:
    _ = draft_values
    from pallas.core.shared.ai_runtime_failure import (
        CIRCUIT_CLOSED,
        CIRCUIT_HALF_OPEN,
        CIRCUIT_OPEN,
        HEALTH_DEGRADED,
        HEALTH_HEALTHY,
        RUNTIME_DEGRADED,
        RUNTIME_HEALTHY,
    )
    from pallas.product.llm.ai_health_parse import (
        llm_health_configuration_ok,
        llm_health_runtime_detail,
        llm_health_summary,
    )
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.startup_probe import probe_ai_service_health

    cfg = get_llm_config()
    if not (
        cfg.llm_chat_enabled
        or cfg.llm_fallback_enabled
        or cfg.llm_polish_enabled
        or cfg.llm_select_enabled
        or cfg.llm_polish_lite_enabled
    ):
        return [
            llm_runtime_result(
                ok=False,
                latency_ms=None,
                status_code=None,
                error="LLM 相关开关均为关",
                runtime_state=RUNTIME_DISABLED,
                runtime_detail="LLM 相关开关均为关",
                failure_class=FAILURE_RUNTIME_DISABLED,
                disabled_health_state=HEALTH_UNKNOWN,
            ),
        ]

    started = time.perf_counter()
    result = await probe_ai_service_health(timeout_sec=min(timeout_sec, 15.0))
    latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
    status_code = result.get("status_code")
    body = result.get("body")
    runtime_detail = llm_health_runtime_detail(body) if isinstance(body, dict) else None
    config_ok = llm_health_configuration_ok(body) if isinstance(body, dict) else None
    llm_summary = llm_health_summary(body) if isinstance(body, dict) else None
    health_state = (llm_summary or {}).get("health_state")
    circuit_state = (llm_summary or {}).get("circuit_state") or CIRCUIT_CLOSED
    recent_failure_class = (llm_summary or {}).get("recent_failure_class")
    if health_state == "degraded":
        probe_health = HEALTH_DEGRADED
    elif health_state == "healthy":
        probe_health = HEALTH_HEALTHY
    else:
        probe_health = None
    if health_state in {"degraded", "unhealthy"}:
        probe_runtime = RUNTIME_DEGRADED
    elif health_state == "healthy":
        probe_runtime = RUNTIME_HEALTHY
    else:
        probe_runtime = None
    if result.get("ok") and config_ok is False:
        return [
            llm_runtime_result(
                ok=False,
                latency_ms=latency_ms,
                status_code=int(status_code) if status_code is not None else None,
                error=runtime_detail or "LLM 配置异常",
                runtime_state=RUNTIME_DEGRADED,
                runtime_detail=runtime_detail,
                failure_class=FAILURE_RUNTIME_DEGRADED,
                disabled_health_state=HEALTH_DEGRADED,
                health_state=probe_health or HEALTH_DEGRADED,
                circuit_state=circuit_state if circuit_state in {CIRCUIT_OPEN, CIRCUIT_HALF_OPEN} else CIRCUIT_OPEN,
                recent_failure_class=recent_failure_class,
            ),
        ]
    if result.get("ok"):
        return [
            llm_runtime_result(
                ok=health_state not in {"degraded", "unhealthy"},
                latency_ms=latency_ms,
                status_code=int(status_code) if status_code is not None else None,
                error=None if health_state not in {"degraded", "unhealthy"} else runtime_detail,
                runtime_state=probe_runtime or RUNTIME_HEALTHY,
                runtime_detail=runtime_detail or "健康检查通过",
                health_state=probe_health or HEALTH_HEALTHY,
                circuit_state=circuit_state,
                recent_failure_class=recent_failure_class,
            ),
        ]
    error = None if isinstance(status_code, int) else normalize_llm_probe_error(result.get("error"))
    return [
        llm_runtime_result(
            ok=False,
            latency_ms=latency_ms if latency_ms > 0 else None,
            status_code=int(status_code) if isinstance(status_code, int) else None,
            error=error,
            failure_class=FAILURE_UPSTREAM_HTTP_ERROR
            if isinstance(status_code, int)
            else (failure_class_from_error(error) or FAILURE_RUNTIME_UNAVAILABLE),
        ),
    ]


def normalize_llm_probe_error(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return "不可用"
    lowered = text.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "超时"
    if "connect" in lowered:
        return "连接失败"
    return text[:120]


register_service_probe_provider(
    ServiceProbeProvider(name="llm", probe=probe_llm_service, priority=10),
)
