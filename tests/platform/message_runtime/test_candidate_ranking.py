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
                "direct_handled": 0,
                "direct_error": 0,
                "ingress_duration_ms_p95": 8.0,
            },
            {
                "route_modules": ["drink"],
                "messages": 14,
                "route_index_hits": 14,
                "route_index_fallbacks": 0,
                "matchers_selected": 28,
                "direct_handled": 0,
                "direct_error": 0,
                "ingress_duration_ms_p95": 25.0,
            },
        ],
        passive_modules={"drink"},
        risk_labels_by_module={"roulette": ["stateful_side_effects"]},
        built_in_modules={"drink", "roulette"},
        direct_modules={"drink"},
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
    assert drink["direct_error"] == 0
    assert drink["eligible"] is True
    assert drink["blockers"] == []
    assert "passive_frequency_inflated" in drink["risk_labels"]
    assert drink["ownership"] == "built_in"
    assert drink["runtime_path"] == "direct"


def test_candidate_ranking_reports_fixed_blockers_without_raising() -> None:
    report = rank_message_runtime_candidates(
        plugin_stats=[],
        route_candidates=[
            {
                "route_modules": ["request_handler"],
                "messages": 3,
                "route_index_fallbacks": 1,
                "matchers_selected": 3,
                "direct_error": 1,
            },
            {"route_modules": ["a", "b"], "messages": 2, "matchers_selected": 4},
            {"route_modules": [], "messages": 1, "matchers_selected": 2},
            "malformed",
        ],
        private_only_modules={"request_handler"},
        complex_request_modules={"request_handler"},
        built_in_modules={"request_handler"},
        matcher_only_modules={"request_handler"},
        day_key="2026-08-10",
        generated_at=123,
        route_window={},
    )

    request = next(row for row in report["candidates"] if row["module"] == "request_handler")
    assert request["estimated_matchers_avoided_today"] is None
    assert request["blockers"] == [
        "route_index_fallback",
        "direct_error",
        "missing_plugin_stats",
        "private_only",
        "complex_request_flow",
        "intentionally_matcher_only",
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
        built_in_modules={"drink"},
    )

    row = report["candidates"][0]
    assert row["estimated_matchers_avoided_today"] == 0.0
    assert row["current_day_duration_ms"] == 0.0
    assert row["ingress_duration_ms_p95"] is None
    assert row["errors_today"] == 1


def test_candidate_ranking_combines_native_history_with_direct_counts() -> None:
    report = rank_message_runtime_candidates(
        plugin_stats=[{"module": "drink", "runs": 3, "runs_today": 3}],
        route_candidates=[
            {
                "route_modules": ["drink"],
                "messages": 3,
                "native_handled": 1,
                "direct_handled": 2,
                "native_fallback": 1,
                "direct_fallback": 2,
                "native_error": 1,
                "direct_error": 2,
                "legacy_handled": 1,
                "matcher_handled": 2,
                "outcomes": {
                    "direct_handled": {
                        "messages": 3,
                        "matchers_selected": 0,
                        "matchers_run": 0,
                        "ingress_duration_ms_p95": 10.0,
                    },
                    "direct_fallback": {
                        "messages": 3,
                        "matchers_selected": 9,
                        "matchers_run": 9,
                        "ingress_duration_ms_p95": 50.0,
                    },
                },
            }
        ],
        day_key="2026-08-10",
        generated_at=123,
        route_window={},
    )

    row = report["candidates"][0]
    assert row["direct_handled"] == 3
    assert row["direct_fallback"] == 3
    assert row["direct_error"] == 3
    assert row["matcher_handled"] == 3
    assert row["outcomes"]["direct_handled"]["ingress_duration_ms_p95"] == 10.0
    assert row["outcomes"]["direct_fallback"]["matchers_selected"] == 9
    assert "already_direct" in row["blockers"]


def test_candidate_ranking_keeps_community_visible_but_not_core_eligible() -> None:
    report = rank_message_runtime_candidates(
        plugin_stats=[{"module": "interact", "runs": 10, "runs_today": 2}],
        route_candidates=[{"route_modules": ["interact"], "messages": 2, "matchers_selected": 2}],
        built_in_modules={"drink"},
        official_extension_modules={"sing"},
        day_key="2026-08-10",
        generated_at=123,
        route_window={},
    )

    row = report["candidates"][0]
    assert row["ownership"] == "community_or_local"
    assert row["runtime_path"] == "matcher"
    assert row["eligible"] is False
    assert "community_or_local" in row["blockers"]
