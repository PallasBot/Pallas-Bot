from __future__ import annotations

import pytest

from pallas.core.platform.message_runtime.handlers import NativeHandlerRegistry
from pallas.core.platform.message_runtime.models import HandlingPlan, MessageContext, RuntimeMode
from pallas.core.platform.message_runtime.planner import MessagePlanner
from pallas.core.platform.message_runtime.runtime import MessageRuntime
from pallas.core.platform.message_runtime.shadow import LegacyExecution


class _Writer:
    def __init__(self) -> None:
        self.records = []

    def record(self, record) -> None:
        self.records.append(record)


def _context() -> MessageContext:
    return MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="#pallas",
        raw_text="#pallas",
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"pb_core"}),
    )


@pytest.mark.asyncio
async def test_shadow_experiment_only_plans_then_records_legacy_result() -> None:
    from pallas.core.platform.message_runtime.experiment import ShadowExperiment

    writer = _Writer()
    runtime = MessageRuntime(RuntimeMode.SHADOW, MessagePlanner(NativeHandlerRegistry()), NativeHandlerRegistry())
    experiment = ShadowExperiment(runtime, writer)

    plan = await experiment.plan(_context())
    experiment.record_legacy(
        _context(),
        plan,
        LegacyExecution(handler_ids=("pb_core",), handled=True, visible_actions=1),
        timestamp=100,
    )

    assert plan == HandlingPlan(kind="legacy", handler_ids=(), reason="unique_route_unregistered")
    assert writer.records[0].kind == "agreement"
    assert writer.records[0].timestamp == 100
