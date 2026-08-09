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
    error_class: str | None = None


@dataclass(frozen=True, slots=True)
class ShadowRecord:
    ingress_id: str
    timestamp: int
    kind: str
    plan_kind: str | None = None
    plan_reason: str | None = None
    handler_ids: tuple[str, ...] = ()
    error_class: str | None = None
    action_count: int | None = None
    duration_ms: float | None = None

    def as_dict(self) -> dict[str, str | int | list[str]]:
        record: dict[str, str | int] = {
            "event_id_hash": self.ingress_id,
            "ts": self.timestamp,
            "kind": self.kind,
        }
        if self.plan_kind:
            record["plan_kind"] = self.plan_kind
        if self.plan_reason:
            record["plan_reason"] = self.plan_reason
        if self.handler_ids:
            record["handler_ids"] = list(self.handler_ids)
        if self.error_class:
            record["error_class"] = self.error_class
        if self.action_count is not None:
            record["action_count"] = self.action_count
        if self.duration_ms is not None:
            record["duration_ms"] = self.duration_ms
        return record


def compare_plan_to_legacy(
    plan: HandlingPlan,
    legacy: LegacyExecution,
    *,
    ingress_id: str,
    timestamp: int = 0,
) -> ShadowRecord:
    if legacy.error_class:
        kind = "legacy_error"
    elif plan.kind == "legacy":
        kind = "agreement"
    elif plan.handler_ids != legacy.handler_ids:
        kind = "route_mismatch"
    elif plan.kind == "native" and not legacy.handled:
        kind = "handled_mismatch"
    else:
        kind = "agreement"
    return ShadowRecord(ingress_id=ingress_id, timestamp=timestamp, kind=kind)
