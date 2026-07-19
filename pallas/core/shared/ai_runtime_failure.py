from __future__ import annotations

from typing import Literal

FAILURE_TIMEOUT = "timeout"
FAILURE_CONNECTION_FAILED = "connection_failed"
FAILURE_RUNTIME_UNAVAILABLE = "runtime_unavailable"
FAILURE_RUNTIME_DISABLED = "runtime_disabled"
FAILURE_RUNTIME_DEGRADED = "runtime_degraded"
FAILURE_RUNTIME_OVERLOADED = "runtime_overloaded"
FAILURE_UPSTREAM_HTTP_ERROR = "upstream_http_error"
FAILURE_UNKNOWN = "unknown"

HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_UNHEALTHY = "unhealthy"
HEALTH_UNKNOWN = "unknown"

CIRCUIT_CLOSED = "closed"
CIRCUIT_OPEN = "open"
CIRCUIT_HALF_OPEN = "half_open"
CIRCUIT_UNKNOWN = "unknown"

RUNTIME_HEALTHY = "healthy"
RUNTIME_DEGRADED = "degraded"
RUNTIME_DISABLED = "disabled"
RUNTIME_UNKNOWN = "unknown"

AiFailureClass = Literal[
    "timeout",
    "connection_failed",
    "runtime_unavailable",
    "runtime_disabled",
    "runtime_degraded",
    "runtime_overloaded",
    "upstream_http_error",
    "unknown",
]

AiHealthState = Literal["healthy", "degraded", "unhealthy", "unknown"]
AiCircuitState = Literal["closed", "open", "half_open", "unknown"]
AiRuntimeState = Literal["healthy", "degraded", "disabled", "unknown"]


def failure_class_from_error(error: str | None) -> AiFailureClass | None:
    text = (error or "").strip().lower()
    if not text:
        return None
    if "超时" in text or "timeout" in text:
        return FAILURE_TIMEOUT
    if "连接失败" in text or "connect" in text:
        return FAILURE_CONNECTION_FAILED
    if "未启用" in text or "disabled" in text:
        return FAILURE_RUNTIME_DISABLED
    if "熔断" in text or "降级" in text:
        return FAILURE_RUNTIME_DEGRADED
    if "http " in text:
        return FAILURE_UPSTREAM_HTTP_ERROR
    return FAILURE_UNKNOWN
