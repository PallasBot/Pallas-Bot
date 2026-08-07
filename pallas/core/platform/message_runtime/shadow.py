from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import HandlingPlan


@dataclass(frozen=True, slots=True)
class LegacyExecution:
    handler_ids: tuple[str, ...]
    handled: bool
    visible_actions: int


@dataclass(frozen=True, slots=True)
class ShadowRecord:
    ingress_id: str
    timestamp: int
    kind: str
    error_class: str | None = None

    def as_dict(self) -> dict[str, str | int]:
        record: dict[str, str | int] = {
            "ingress_id": self.ingress_id,
            "ts": self.timestamp,
            "kind": self.kind,
        }
        if self.error_class:
            record["error_class"] = self.error_class
        return record


def compare_plan_to_legacy(
    plan: HandlingPlan,
    legacy: LegacyExecution,
    *,
    ingress_id: str,
    timestamp: int = 0,
) -> ShadowRecord:
    if plan.handler_ids != legacy.handler_ids:
        kind = "route_mismatch"
    elif plan.kind == "native" and not legacy.handled:
        kind = "handled_mismatch"
    else:
        kind = "agreement"
    return ShadowRecord(ingress_id=ingress_id, timestamp=timestamp, kind=kind)
