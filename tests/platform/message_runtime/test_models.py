from __future__ import annotations

import pytest

from pallas.core.platform.message_runtime.models import (
    CrossWorkerAction,
    DeferredAction,
    HandlingOutcome,
    HandlingPlan,
    MessageContext,
    RuntimeMode,
    SendAction,
)
from pallas.core.platform.work_jobs.models import WorkJob


def test_runtime_mode_uses_permanent_execution_path_names() -> None:
    assert RuntimeMode.MATCHER == "matcher"
    assert RuntimeMode.SHADOW == "shadow"
    assert RuntimeMode.DIRECT == "direct"


@pytest.mark.parametrize(
    ("old_value", "expected"),
    [("legacy", RuntimeMode.MATCHER), ("native", RuntimeMode.DIRECT)],
)
def test_runtime_mode_reads_temporary_names_as_compatibility_aliases(
    old_value: str,
    expected: RuntimeMode,
) -> None:
    assert RuntimeMode(old_value) is expected


def test_fallback_outcome_cannot_contain_actions() -> None:
    with pytest.raises(ValueError, match="fallback"):
        HandlingOutcome(
            handled=False,
            fallback_to_matcher=True,
            actions=(SendAction(message="reply"),),
        )


def test_fallback_outcome_cannot_contain_deferred_actions() -> None:
    with pytest.raises(ValueError, match="fallback"):
        HandlingOutcome(
            handled=False,
            fallback_to_matcher=True,
            deferred_actions=(DeferredAction(name="reply", run=lambda: None),),
        )


def test_fallback_reason_requires_matcher_fallback() -> None:
    with pytest.raises(ValueError, match="fallback reason"):
        HandlingOutcome(handled=True, fallback_reason="no_reply_bundle")


def test_cross_worker_action_requires_target_and_idempotency_key() -> None:
    with pytest.raises(ValueError, match="target"):
        CrossWorkerAction(kind="repeater.fanout_reply", target_bot_id=0, payload={}, idempotency_key="fanout:1")
    with pytest.raises(ValueError, match="idempotency"):
        CrossWorkerAction(kind="repeater.fanout_reply", target_bot_id=1, payload={}, idempotency_key="")


def test_fallback_outcome_cannot_contain_cross_worker_actions() -> None:
    with pytest.raises(ValueError, match="fallback"):
        HandlingOutcome(
            handled=False,
            fallback_to_matcher=True,
            cross_worker_actions=(
                CrossWorkerAction(
                    kind="repeater.fanout_reply",
                    target_bot_id=1,
                    payload={},
                    idempotency_key="fanout:1",
                ),
            ),
        )


def test_fallback_outcome_cannot_contain_work_jobs() -> None:
    job = WorkJob.create(kind="repeater.learn", payload={"message_id": 3}, idempotency_key="repeater.learn:3")

    with pytest.raises(ValueError, match="fallback"):
        HandlingOutcome(
            handled=False,
            fallback_to_matcher=True,
            work_jobs=(job,),
        )


def test_handled_outcome_can_continue_matcher_without_its_own_module() -> None:
    outcome = HandlingOutcome(
        handled=True,
        continue_matcher=True,
        matcher_exclude_modules=frozenset({"repeater"}),
    )

    assert outcome.continue_matcher is True
    assert outcome.matcher_exclude_modules == frozenset({"repeater"})


def test_message_context_telemetry_redacts_message_content() -> None:
    context = MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="secret message",
        raw_text="secret message",
        is_to_me=False,
        command_traffic=False,
        route_modules=frozenset(),
    )

    fields = context.telemetry_fields()

    assert fields["event_id_hash"] != "i-1"
    assert fields["bot_id_hash"] != "1"
    assert fields["group_id_hash"] != "2"
    assert "secret message" not in fields.values()


def test_handling_plan_requires_a_reason_for_matcher_fallback() -> None:
    with pytest.raises(ValueError, match="reason"):
        HandlingPlan(kind="matcher", handler_ids=(), reason="")


def test_temporary_outcome_names_remain_readable() -> None:
    outcome = HandlingOutcome(
        handled=True,
        continue_matcher=True,
        matcher_exclude_modules=frozenset({"drink"}),
    )

    assert outcome.continue_legacy is True
    assert outcome.legacy_exclude_modules == frozenset({"drink"})
