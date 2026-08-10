from __future__ import annotations

import pytest

from pallas.core.platform.message_runtime.handlers import RuntimeHandlerRegistry
from pallas.core.platform.message_runtime.models import HandlingPlan, MessageContext, RuntimeMode
from pallas.core.platform.message_runtime.planner import MessagePlanner
from pallas.core.platform.message_runtime.runtime import MessageRuntime
from pallas.core.platform.message_runtime.shadow import MatcherExecution


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
async def test_shadow_experiment_only_plans_then_records_matcher_result() -> None:
    from pallas.core.platform.message_runtime.experiment import ShadowExperiment

    writer = _Writer()
    runtime = MessageRuntime(RuntimeMode.SHADOW, MessagePlanner(RuntimeHandlerRegistry()), RuntimeHandlerRegistry())
    experiment = ShadowExperiment(runtime, writer)

    plan = await experiment.plan(_context())
    experiment.record_matcher(
        _context(),
        plan,
        MatcherExecution(handler_ids=("pb_core",), handled=True, visible_actions=1),
        timestamp=100,
    )

    assert plan == HandlingPlan(kind="matcher", handler_ids=(), reason="unique_route_unregistered")
    record = writer.records[0]
    assert record.kind == "agreement"
    assert record.timestamp == 100
    assert record.ingress_id == _context().telemetry_fields()["event_id_hash"]
    assert record.plan_kind == "matcher"
    assert record.plan_reason == "unique_route_unregistered"
