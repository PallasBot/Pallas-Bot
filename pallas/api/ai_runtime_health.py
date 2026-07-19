"""插件读取 AI runtime 健康/熔断的唯一入口（事实源 = AI /health）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pallas.core.shared.ai_health_cache import cached_ai_health_body
from pallas.product.llm.ai_health_parse import capability_health_circuit, image_health_circuit


@dataclass(frozen=True, slots=True)
class ImageRuntimeCircuitSnapshot:
    consecutive_failures: int = 0
    last_failure_at: float = 0.0
    last_success_at: float = 0.0
    circuit_open_until: float = 0.0
    recent_failure_reason: str = ""


def image_health_circuit_from_cache() -> dict[str, Any] | None:
    return image_health_circuit(cached_ai_health_body())


def image_runtime_circuit_is_open() -> bool:
    circuit = image_health_circuit_from_cache()
    if not circuit:
        return False
    return str(circuit.get("circuit_state") or "").strip().lower() == "open"


def image_runtime_circuit_snapshot() -> ImageRuntimeCircuitSnapshot:
    circuit = image_health_circuit_from_cache()
    if not circuit:
        return ImageRuntimeCircuitSnapshot()
    return ImageRuntimeCircuitSnapshot(
        consecutive_failures=int(circuit.get("consecutive_failures") or 0),
        recent_failure_reason=str(circuit.get("recent_failure_class") or circuit.get("recent_failure_reason") or ""),
    )


def sing_health_circuit_from_cache() -> dict[str, Any] | None:
    return capability_health_circuit(cached_ai_health_body(), "media.sing")


def llm_health_circuit_from_cache() -> dict[str, Any] | None:
    from pallas.product.llm.ai_health_parse import llm_health_circuit

    return llm_health_circuit(cached_ai_health_body())


def llm_runtime_circuit_is_open() -> bool:
    circuit = llm_health_circuit_from_cache()
    if not circuit:
        return False
    return str(circuit.get("circuit_state") or "").strip().lower() == "open"
