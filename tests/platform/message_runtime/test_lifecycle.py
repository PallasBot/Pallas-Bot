from __future__ import annotations

import json

from pallas.core.platform.message_runtime import lifecycle
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext, RuntimeMode, SendAction


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
        mode=RuntimeMode.NATIVE,
        canary_groups=(100,),
        telemetry_enabled=True,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    assert lifecycle.shadow_experiment_for_group(100) is None


def test_native_runtime_is_limited_to_configured_canary_groups() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.NATIVE,
        canary_groups=(100,),
        telemetry_enabled=False,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    assert lifecycle.native_runtime_for_group(100) is not None
    assert lifecycle.native_runtime_for_group(999) is None


def test_native_runtime_uses_all_groups_when_canary_groups_is_empty() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.NATIVE,
        canary_groups=(),
        telemetry_enabled=False,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    assert lifecycle.native_runtime_for_group(100) is not None
    assert lifecycle.native_runtime_for_group(999) is not None


def test_native_runtime_registers_repeater_as_a_passive_handler() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.NATIVE,
        canary_groups=(100,),
        telemetry_enabled=False,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    runtime = lifecycle.native_runtime_for_group(100)

    assert runtime is not None
    assert runtime._registry.get("repeater.message") is not None  # noqa: SLF001


def test_native_runtime_registers_llm_chat_as_a_passive_handler() -> None:
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.NATIVE,
        canary_groups=(100,),
        telemetry_enabled=False,
        retention_hours=24,
        agreement_sample_rate=1,
    )

    runtime = lifecycle.native_runtime_for_group(100)

    assert runtime is not None
    assert runtime._registry.get("llm_chat.message") is not None  # noqa: SLF001


def test_native_execution_persists_outcome_without_message_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lifecycle, "message_runtime_experiment_path", lambda: tmp_path / "experiment.jsonl")
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.NATIVE,
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

    lifecycle.record_native_execution(
        context,
        HandlingOutcome(handled=True, actions=(SendAction("reply"),)),
        duration_ms=1.25,
        timestamp=100,
    )
    lifecycle.flush_shadow_experiment()

    row = json.loads((tmp_path / "experiment.jsonl").read_text(encoding="utf-8"))

    assert row == {
        "event_id_hash": context.telemetry_fields()["event_id_hash"],
        "ts": 100,
        "kind": "native_handled",
        "action_count": 1,
        "duration_ms": 1.25,
    }
    assert "1:100:3" not in row.values()


def test_native_execution_persists_handler_errors_without_message_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lifecycle, "message_runtime_experiment_path", lambda: tmp_path / "experiment.jsonl")
    lifecycle.configure_shadow_experiment(
        mode=RuntimeMode.NATIVE,
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

    lifecycle.record_native_execution(
        context,
        HandlingOutcome(handled=False, fallback_to_legacy=True, error_class="RuntimeError"),
        duration_ms=1.25,
        timestamp=100,
    )
    lifecycle.flush_shadow_experiment()

    row = json.loads((tmp_path / "experiment.jsonl").read_text(encoding="utf-8"))

    assert row == {
        "event_id_hash": context.telemetry_fields()["event_id_hash"],
        "ts": 100,
        "kind": "native_error",
        "error_class": "RuntimeError",
        "action_count": 0,
        "duration_ms": 1.25,
    }
    assert "1:100:3" not in row.values()
