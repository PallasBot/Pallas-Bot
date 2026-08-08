from __future__ import annotations

from pallas.core.platform.message_runtime import lifecycle
from pallas.core.platform.message_runtime.models import RuntimeMode


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
