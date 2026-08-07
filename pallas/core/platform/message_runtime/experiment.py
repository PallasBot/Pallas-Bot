from __future__ import annotations

from typing import TYPE_CHECKING

from .shadow import compare_plan_to_legacy

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
        self._writer.record(compare_plan_to_legacy(plan, legacy, ingress_id=context.ingress_id, timestamp=timestamp))
