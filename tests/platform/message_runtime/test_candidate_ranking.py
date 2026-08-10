from __future__ import annotations

from pallas.core.platform.message_runtime.candidate_ranking import rank_message_runtime_candidates


def test_candidate_ranking_calculates_benefit_and_orders_eligible_rows() -> None:
    report = rank_message_runtime_candidates(
        plugin_stats=[
            {"module": "drink", "runs": 100, "runs_today": 28, "duration_ms_today": 4495.0},
            {"module": "roulette", "runs": 50, "runs_today": 11, "duration_ms_today": 39.0},
        ],
        route_candidates=[
            {
                "route_modules": ["roulette"],
                "messages": 10,
                "route_index_hits": 10,
                "route_index_fallbacks": 0,
                "matchers_selected": 10,
                "native_handled": 0,
                "native_error": 0,
                "ingress_duration_ms_p95": 8.0,
            },
            {
                "route_modules": ["drink"],
                "messages": 14,
                "route_index_hits": 14,
                "route_index_fallbacks": 0,
                "matchers_selected": 28,
                "native_handled": 0,
                "native_error": 0,
                "ingress_duration_ms_p95": 25.0,
            },
        ],
        passive_modules={"drink"},
        risk_labels_by_module={"roulette": ["stateful_side_effects"]},
        day_key="2026-08-10",
        generated_at=123,
        route_window={"retention_sec": 604800, "latest_at": 120},
    )

    assert [row["module"] for row in report["candidates"]] == ["drink", "roulette"]
    drink = report["candidates"][0]
    assert drink["estimated_matchers_avoided_today"] == 56.0
    assert drink["average_matchers_selected_per_route_message"] == 2.0
    assert drink["current_day_duration_ms"] == 4495.0
    assert drink["route_index_hits"] == 14
    assert drink["matchers_selected"] == 28
    assert drink["native_error"] == 0
    assert drink["eligible"] is True
    assert drink["blockers"] == []
    assert "passive_frequency_inflated" in drink["risk_labels"]


def test_candidate_ranking_reports_fixed_blockers_without_raising() -> None:
    report = rank_message_runtime_candidates(
        plugin_stats=[],
        route_candidates=[
            {
                "route_modules": ["request_handler"],
                "messages": 3,
                "route_index_fallbacks": 1,
                "matchers_selected": 3,
                "native_error": 1,
            },
            {"route_modules": ["a", "b"], "messages": 2, "matchers_selected": 4},
            {"route_modules": [], "messages": 1, "matchers_selected": 2},
            "malformed",
        ],
        private_only_modules={"request_handler"},
        complex_request_modules={"request_handler"},
        day_key="2026-08-10",
        generated_at=123,
        route_window={},
    )

    request = next(row for row in report["candidates"] if row["module"] == "request_handler")
    assert request["estimated_matchers_avoided_today"] is None
    assert request["blockers"] == [
        "route_index_fallback",
        "native_error",
        "missing_plugin_stats",
        "private_only",
        "complex_request_flow",
    ]
    assert request["eligible"] is False
    multi = next(row for row in report["candidates"] if row["module"] == "a,b")
    unidentified = next(row for row in report["candidates"] if row["module"] == "")
    assert "multiple_route_modules" in multi["blockers"]
    assert "insufficient_route_identity" in unidentified["blockers"]
    assert "missing_plugin_stats" in report["data_quality"]


def test_candidate_ranking_returns_zero_estimate_and_sanitizes_non_finite_values() -> None:
    report = rank_message_runtime_candidates(
        plugin_stats=[
            {
                "module": "drink",
                "runs": 1,
                "runs_today": 2,
                "duration_ms_today": float("inf"),
                "errors_today": 1,
            }
        ],
        route_candidates=[
            {
                "route_modules": ["drink"],
                "messages": 2,
                "matchers_selected": 0,
                "ingress_duration_ms_p95": float("nan"),
            }
        ],
        day_key="2026-08-10",
        generated_at=123,
        route_window={},
    )

    row = report["candidates"][0]
    assert row["estimated_matchers_avoided_today"] == 0.0
    assert row["current_day_duration_ms"] == 0.0
    assert row["ingress_duration_ms_p95"] is None
    assert row["errors_today"] == 1
