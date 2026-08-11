from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    workload_id: str
    messages: int
    visible_actions: int | None
    errors: int
    fallbacks: int
    degraded: int
    matcher_work: int | None
    ingress_duration_ms_p95: float | None


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    eligible: bool
    reason: str
    matcher_work_delta: int | None
    ingress_p95_delta_ms: float | None


def evaluate_candidate_replay(legacy: ReplaySummary, candidate: ReplaySummary) -> ReplayDecision:
    matcher_delta = measurement_delta(legacy.matcher_work, candidate.matcher_work)
    p95_delta = measurement_delta(legacy.ingress_duration_ms_p95, candidate.ingress_duration_ms_p95)

    def decision(eligible: bool, reason: str) -> ReplayDecision:
        return ReplayDecision(eligible, reason, matcher_delta, p95_delta)

    if not summaries_have_measurements(legacy, candidate):
        return decision(False, "missing_measurement")
    if legacy.workload_id != candidate.workload_id or legacy.messages != candidate.messages:
        return decision(False, "workload_mismatch")
    if legacy.visible_actions != candidate.visible_actions:
        return decision(False, "visible_action_divergence")
    if candidate.errors / candidate.messages >= 0.0001:
        return decision(False, "candidate_error_rate")
    if candidate.fallbacks > legacy.fallbacks or candidate.degraded > legacy.degraded:
        return decision(False, "fallback_regression")
    if not ((matcher_delta is not None and matcher_delta < 0) or (p95_delta is not None and p95_delta < 0)):
        return decision(False, "no_useful_improvement")
    return decision(True, "ready")


def summaries_have_measurements(legacy: ReplaySummary, candidate: ReplaySummary) -> bool:
    for summary in (legacy, candidate):
        if (
            not summary.workload_id
            or summary.messages <= 0
            or summary.visible_actions is None
            or summary.visible_actions < 0
            or summary.errors < 0
            or summary.fallbacks < 0
            or summary.degraded < 0
            or (summary.matcher_work is not None and summary.matcher_work < 0)
            or (summary.ingress_duration_ms_p95 is not None and summary.ingress_duration_ms_p95 < 0)
        ):
            return False
    return (
        legacy.matcher_work is not None
        and candidate.matcher_work is not None
        or (legacy.ingress_duration_ms_p95 is not None and candidate.ingress_duration_ms_p95 is not None)
    )


def measurement_delta(legacy: int | float | None, candidate: int | float | None):
    if legacy is None or candidate is None:
        return None
    return candidate - legacy
