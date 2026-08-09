from __future__ import annotations

from pallas.core.platform.message_runtime.models import HandlingPlan
from pallas.core.platform.message_runtime.shadow import LegacyExecution, compare_plan_to_legacy


def test_shadow_marks_different_route_as_a_mismatch() -> None:
    record = compare_plan_to_legacy(
        HandlingPlan(kind="native", handler_ids=("pb_core.status",), reason="unique_command"),
        LegacyExecution(handler_ids=("help.help",), handled=True, visible_actions=1),
        ingress_id="i-1",
    )

    assert record.kind == "route_mismatch"
    assert record.ingress_id == "i-1"


def test_shadow_marks_equivalent_route_and_result_as_agreement() -> None:
    record = compare_plan_to_legacy(
        HandlingPlan(kind="native", handler_ids=("pb_core.status",), reason="unique_command"),
        LegacyExecution(handler_ids=("pb_core.status",), handled=True, visible_actions=1),
        ingress_id="i-2",
    )

    assert record.kind == "agreement"


def test_shadow_marks_legacy_error_before_route_comparison() -> None:
    record = compare_plan_to_legacy(
        HandlingPlan(kind="native", handler_ids=("pb_core.status",), reason="unique_command"),
        LegacyExecution(
            handler_ids=("pb_core.status",),
            handled=True,
            visible_actions=1,
            error_class="RuntimeError",
        ),
        ingress_id="i-4",
    )

    assert record.kind == "legacy_error"
