from __future__ import annotations

import json

from pallas.api.runtime import register_exact_command_handler, reply, reset_exact_command_handlers
from pallas.core.platform.message_runtime import lifecycle
from pallas.core.platform.message_runtime.models import (
    CrossWorkerAction,
    DeferredAction,
    HandlingOutcome,
    MessageContext,
    RuntimeMode,
    SendAction,
)
from pallas.core.platform.work_jobs.models import WorkJob


def setup_function() -> None:
    lifecycle.reset_shadow_experiment_for_tests()


def teardown_function() -> None:
    lifecycle.reset_shadow_experiment_for_tests()


def test_shadow_experiment_is_limited_to_configured_canary_groups(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lifecycle, "message_runtime_experiment_path", lambda: tmp_path / "experiment.jsonl")

    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.SHADOW,
        canary_groups=(100, 200),
        telemetry_enabled=True,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    assert lifecycle.shadow_experiment_for_group(100) is not None
    assert lifecycle.shadow_experiment_for_group(999) is None


def test_native_mode_does_not_activate_shadow_experiment() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.DIRECT,
        canary_groups=(100,),
        telemetry_enabled=True,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    assert lifecycle.shadow_experiment_for_group(100) is None


def test_direct_runtime_is_limited_to_configured_canary_groups() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.DIRECT,
        canary_groups=(100,),
        telemetry_enabled=False,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    assert lifecycle.direct_runtime_for_group(100) is not None
    assert lifecycle.direct_runtime_for_group(999) is None


def test_direct_runtime_uses_all_groups_when_canary_groups_is_empty() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.DIRECT,
        canary_groups=(),
        telemetry_enabled=False,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    assert lifecycle.direct_runtime_for_group(100) is not None
    assert lifecycle.direct_runtime_for_group(999) is not None


def test_direct_runtime_registers_repeater_as_a_passive_handler() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.DIRECT,
        canary_groups=(100,),
        telemetry_enabled=False,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    runtime = lifecycle.direct_runtime_for_group(100)

    assert runtime is not None
    assert runtime._registry.get("repeater.message") is not None  # noqa: SLF001


def test_direct_runtime_registers_llm_chat_as_a_passive_handler() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.DIRECT,
        canary_groups=(100,),
        telemetry_enabled=False,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    runtime = lifecycle.direct_runtime_for_group(100)

    assert runtime is not None
    assert runtime._registry.get("llm_chat.message") is not None  # noqa: SLF001


def test_direct_runtime_registers_drink_as_the_only_handler_for_drink_commands() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.DIRECT,
        canary_groups=(100,),
        telemetry_enabled=False,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    runtime = lifecycle.direct_runtime_for_group(100)
    context = MessageContext(
        ingress_id="1:100:3",
        bot_id=1,
        group_id=100,
        message_id=3,
        plain_text="牛牛干杯",
        raw_text="牛牛干杯",
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"drink"}),
    )

    assert runtime is not None
    assert runtime._registry.get("drink.direct") is not None  # noqa: SLF001
    assert runtime._registry.handler_ids_for_context(context) == ("drink.direct",)  # noqa: SLF001


def test_direct_runtime_snapshots_public_exact_command_declarations() -> None:
    async def execute(_context):
        return reply("ok")

    reset_exact_command_handlers()
    register_exact_command_handler(
        handler_id="roulette.public",
        module="roulette",
        commands=("牛牛轮盘",),
        command_id="roulette.start",
        execute=execute,
    )
    try:
        lifecycle.configure_shadow_experiment(
            mode=RuntimeMode.DIRECT,
            canary_groups=(100,),
            telemetry_enabled=False,
            retention_hours=24,
            agreement_sample_rate=1,
        )

        runtime = lifecycle.direct_runtime_for_group(100)

        assert runtime is not None
        assert runtime._registry.get("roulette.public") is not None  # noqa: SLF001
    finally:
        reset_exact_command_handlers()


def test_native_execution_persists_outcome_without_message_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lifecycle, "message_runtime_experiment_path", lambda: tmp_path / "experiment.jsonl")
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.DIRECT,
        canary_groups=(100,),
        telemetry_enabled=True,
        retention_hours=24,
        agreement_sample_rate=1,
    )
    context = MessageContext(
        ingress_id="1:100:3",
        bot_id=1,
        group_id=100,
        message_id=3,
        plain_text="secret command",
        raw_text="secret command",
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"pb_core"}),
    )

    lifecycle.record_direct_execution(
        context,
        HandlingOutcome(
            handled=True,
            handler_id="pb_core.status",
            actions=(SendAction("reply"),),
            work_jobs=(WorkJob.create(kind="test.work", payload={}, idempotency_key="test.work:1"),),
            cross_worker_actions=(
                CrossWorkerAction(
                    kind="repeater.fanout_reply",
                    target_bot_id=2,
                    payload={},
                    idempotency_key="test.fanout:1",
                ),
            ),
            deferred_actions=(DeferredAction(name="test.deferred", run=lambda: __import__("asyncio").sleep(0)),),
        ),
        duration_ms=1.25,
        timestamp=100,
    )
    lifecycle.flush_shadow_experiment()

    row = json.loads((tmp_path / "experiment.jsonl").read_text(encoding="utf-8"))

    assert row == {
        "event_id_hash": context.telemetry_fields()["event_id_hash"],
        "ts": 100,
        "kind": "direct_handled",
        "handler_id": "pb_core.status",
        "action_count": 1,
        "work_job_count": 1,
        "cross_worker_action_count": 1,
        "deferred_action_count": 1,
        "duration_ms": 1.25,
    }
    assert "1:100:3" not in row.values()


def test_native_execution_persists_handler_errors_without_message_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lifecycle, "message_runtime_experiment_path", lambda: tmp_path / "experiment.jsonl")
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.DIRECT,
        canary_groups=(100,),
        telemetry_enabled=True,
        retention_hours=24,
        agreement_sample_rate=1,
    )
    context = MessageContext(
        ingress_id="1:100:3",
        bot_id=1,
        group_id=100,
        message_id=3,
        plain_text="secret command",
        raw_text="secret command",
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"pb_core"}),
    )

    lifecycle.record_direct_execution(
        context,
        HandlingOutcome(handled=False, fallback_to_matcher=True, error_class="RuntimeError"),
        duration_ms=1.25,
        timestamp=100,
    )
    lifecycle.flush_shadow_experiment()

    row = json.loads((tmp_path / "experiment.jsonl").read_text(encoding="utf-8"))

    assert row == {
        "event_id_hash": context.telemetry_fields()["event_id_hash"],
        "ts": 100,
        "kind": "direct_error",
        "error_class": "RuntimeError",
        "action_count": 0,
        "duration_ms": 1.25,
    }
    assert "1:100:3" not in row.values()


def test_native_execution_persists_fallback_reason_without_message_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lifecycle, "message_runtime_experiment_path", lambda: tmp_path / "experiment.jsonl")
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.DIRECT,
        canary_groups=(100,),
        telemetry_enabled=True,
        retention_hours=24,
        agreement_sample_rate=1,
    )
    context = MessageContext(
        ingress_id="1:100:3",
        bot_id=1,
        group_id=100,
        message_id=3,
        plain_text="secret command",
        raw_text="secret command",
        is_to_me=False,
        command_traffic=False,
        route_modules=frozenset({"repeater"}),
    )

    lifecycle.record_direct_execution(
        context,
        HandlingOutcome(
            handled=False,
            handler_id="repeater.message",
            fallback_to_matcher=True,
            fallback_reason="no_reply_bundle",
        ),
        duration_ms=1.25,
        timestamp=100,
    )
    lifecycle.flush_shadow_experiment()

    row = json.loads((tmp_path / "experiment.jsonl").read_text(encoding="utf-8"))

    assert row == {
        "event_id_hash": context.telemetry_fields()["event_id_hash"],
        "ts": 100,
        "kind": "direct_fallback",
        "handler_id": "repeater.message",
        "fallback_reason": "no_reply_bundle",
        "action_count": 0,
        "duration_ms": 1.25,
    }
    assert "secret command" not in row.values()
    assert "1:100:3" not in row.values()
