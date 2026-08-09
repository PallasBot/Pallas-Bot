from __future__ import annotations

from typing import TYPE_CHECKING

from .shadow import ShadowRecord, compare_plan_to_legacy

if TYPE_CHECKING:
    from .models import HandlingPlan, MessageContext
    from .runtime import MessageRuntime
    from .shadow import LegacyExecution
    from .telemetry import ExperimentTelemetryWriter


class ShadowExperiment:
    def __init__(self, runtime: MessageRuntime, writer: ExperimentTelemetryWriter | None = None) -> None:
        self._runtime = runtime
        self._writer = writer

    async def plan(self, context: MessageContext) -> HandlingPlan:
        return await self._runtime.submit(context)

    def record_legacy(
        self,
        context: MessageContext,
        plan: HandlingPlan,
        legacy: LegacyExecution,
        *,
        timestamp: int,
    ) -> None:
        if self._writer is None:
            return
        record = compare_plan_to_legacy(
            plan,
            legacy,
            ingress_id=context.telemetry_fields()["event_id_hash"],
            timestamp=timestamp,
        )
        self._writer.record(
            ShadowRecord(
                ingress_id=record.ingress_id,
                timestamp=record.timestamp,
                kind=record.kind,
                plan_kind=plan.kind,
                plan_reason=plan.reason,
                handler_ids=plan.handler_ids,
                error_class=legacy.error_class,
            )
        )
