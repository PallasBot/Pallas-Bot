from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pallas.core.shared.ai_runtime_failure import (
        AiCircuitState,
        AiFailureClass,
        AiHealthState,
        AiRuntimeState,
    )


@dataclass(frozen=True)
class ServiceProbeResult:
    category: str
    site: str
    ok: bool
    latency_ms: int | None
    status_code: int | None
    error: str | None
    runtime_state: AiRuntimeState | None = None
    runtime_detail: str | None = None
    capability_id: str | None = None
    capability_group: str | None = None
    runtime_type: str | None = None
    failure_class: AiFailureClass | None = None
    health_state: AiHealthState | None = None
    circuit_state: AiCircuitState | None = None
    consecutive_failures: int | None = None
    recent_failure_class: AiFailureClass | None = None
    queue_load_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
