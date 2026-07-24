"""智能对话服务探测（Bot 内核 Provider，不依赖 AI Runtime /health）。"""

from __future__ import annotations

import time

from pallas.core.shared.ai_runtime_capability import LLM_CHAT
from pallas.core.shared.ai_runtime_failure import (
    CIRCUIT_CLOSED,
    CIRCUIT_OPEN,
    FAILURE_RUNTIME_DISABLED,
    FAILURE_RUNTIME_UNAVAILABLE,
    FAILURE_UPSTREAM_HTTP_ERROR,
    HEALTH_HEALTHY,
    HEALTH_UNHEALTHY,
    HEALTH_UNKNOWN,
    RUNTIME_DISABLED,
    RUNTIME_HEALTHY,
    failure_class_from_error,
)
from pallas.core.shared.service_probe import (
    ServiceProbeResult,
    build_runtime_probe_result,
)
from pallas.product.service_gateways.registry import ServiceProbeProvider, register_service_probe_provider

LLM_CATEGORY = "LLM对话"
LLM_SITE = "Provider"


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
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.startup_probe import probe_llm_provider

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
    result = await probe_llm_provider(timeout_sec=min(timeout_sec, 15.0))
    latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
    status_code = result.get("status_code")
    status_code_int = int(status_code) if isinstance(status_code, int) else None

    if result.get("ok"):
        return [
            llm_runtime_result(
                ok=True,
                latency_ms=latency_ms,
                status_code=status_code_int,
                error=None,
                runtime_state=RUNTIME_HEALTHY,
                runtime_detail="Provider 可达",
                health_state=HEALTH_HEALTHY,
                circuit_state=CIRCUIT_CLOSED,
            ),
        ]

    if result.get("configured") is False:
        detail = "尚未配置 Provider"
        return [
            llm_runtime_result(
                ok=False,
                latency_ms=latency_ms if latency_ms > 0 else None,
                status_code=None,
                error=detail,
                runtime_detail=detail,
                failure_class=FAILURE_RUNTIME_UNAVAILABLE,
                health_state=HEALTH_UNHEALTHY,
                circuit_state=CIRCUIT_OPEN,
            ),
        ]

    error = None if status_code_int is not None else normalize_llm_probe_error(result.get("error"))
    return [
        llm_runtime_result(
            ok=False,
            latency_ms=latency_ms if latency_ms > 0 else None,
            status_code=status_code_int,
            error=error,
            failure_class=FAILURE_UPSTREAM_HTTP_ERROR
            if status_code_int is not None
            else (failure_class_from_error(error) or FAILURE_RUNTIME_UNAVAILABLE),
            health_state=HEALTH_UNHEALTHY,
            circuit_state=CIRCUIT_OPEN,
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
    if "missing" in lowered or "configure" in lowered:
        return "尚未配置 Provider"
    return text[:120]


register_service_probe_provider(
    ServiceProbeProvider(name="llm", probe=probe_llm_service, priority=10),
)
