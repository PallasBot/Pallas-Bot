from __future__ import annotations

from dataclasses import replace

from pallas.core.platform.message_runtime.candidate_replay import ReplaySummary, evaluate_candidate_replay


def summary(**overrides) -> ReplaySummary:
    values = {
        "workload_id": "fixture-v1",
        "messages": 20_000,
        "visible_actions": 120,
        "errors": 0,
        "fallbacks": 4,
        "degraded": 2,
        "matcher_work": 60_000,
        "ingress_duration_ms_p95": 40.0,
    }
    values.update(overrides)
    return ReplaySummary(**values)


def test_accepts_equal_workload_with_strict_matcher_improvement() -> None:
    legacy = summary()
    candidate = replace(legacy, matcher_work=20_000, ingress_duration_ms_p95=40.0)

    decision = evaluate_candidate_replay(legacy, candidate)

    assert decision.eligible is True
    assert decision.reason == "ready"
    assert decision.matcher_work_delta == -40_000
    assert decision.ingress_p95_delta_ms == 0.0


def test_blocks_workload_mismatch() -> None:
    decision = evaluate_candidate_replay(summary(), summary(workload_id="fixture-v2"))
    assert (decision.eligible, decision.reason) == (False, "workload_mismatch")


def test_blocks_visible_action_divergence() -> None:
    decision = evaluate_candidate_replay(summary(), summary(visible_actions=119))
    assert decision.reason == "visible_action_divergence"


def test_blocks_candidate_error_rate_at_threshold() -> None:
    decision = evaluate_candidate_replay(summary(), summary(errors=2))
    assert decision.reason == "candidate_error_rate"


def test_blocks_fallback_or_degraded_regression() -> None:
    assert evaluate_candidate_replay(summary(), summary(fallbacks=5)).reason == "fallback_regression"
    assert evaluate_candidate_replay(summary(), summary(degraded=3)).reason == "fallback_regression"


def test_blocks_missing_measurement_without_raising() -> None:
    decision = evaluate_candidate_replay(summary(), summary(ingress_duration_ms_p95=None, matcher_work=None))
    assert decision.reason == "missing_measurement"


def test_blocks_negative_measurements_as_malformed() -> None:
    assert evaluate_candidate_replay(summary(), summary(matcher_work=-1)).reason == "missing_measurement"
    assert evaluate_candidate_replay(summary(), summary(ingress_duration_ms_p95=-1.0)).reason == "missing_measurement"


def test_blocks_when_neither_work_measurement_improves() -> None:
    decision = evaluate_candidate_replay(summary(), summary(matcher_work=60_000, ingress_duration_ms_p95=41.0))
    assert decision.reason == "no_useful_improvement"
