from __future__ import annotations

from pallas.core.platform.ingress import route_candidate_metrics as metrics


def setup_function() -> None:
    metrics.clear_route_candidate_metrics_for_tests()


def record(**overrides) -> None:
    values = {
        "route_modules": frozenset({"zeta", "alpha"}),
        "index_hit": True,
        "route_fallback": False,
        "matchers_considered": 10,
        "matchers_selected": 4,
        "matchers_run": 3,
        "direct_outcome": None,
        "matcher_handled": True,
        "direct_visible_actions": None,
        "direct_effect_actions": None,
        "duration_ms": 10.0,
        "runtime_stages_ms": (),
    }
    values.update(overrides)
    metrics.record_route_candidate(**values)


def test_aggregates_normalized_route_and_exact_counters() -> None:
    record()
    record(
        route_modules=frozenset({"alpha", "zeta"}),
        index_hit=False,
        route_fallback=True,
        matchers_considered=8,
        matchers_selected=2,
        matchers_run=1,
        direct_outcome="direct_handled",
        matcher_handled=False,
        direct_visible_actions=2,
        direct_effect_actions=5,
        duration_ms=20.0,
        runtime_stages_ms=(("handler", 20.0), ("commit", 2.0)),
    )

    row = metrics.route_candidate_metrics_snapshot()[0]
    assert row == {
        "route_modules": ["alpha", "zeta"],
        "messages": 2,
        "route_index_hits": 1,
        "route_index_fallbacks": 1,
        "matchers_considered": 18,
        "matchers_selected": 6,
        "matchers_run": 4,
        "direct_handled": 1,
        "direct_fallback": 0,
        "direct_error": 0,
        "matcher_handled": 1,
        "direct_visible_actions": 2,
        "direct_effect_actions": 5,
        "outcomes": {
            "direct_handled": {
                "messages": 1,
                "matchers_considered": 8,
                "matchers_selected": 2,
                "matchers_run": 1,
                "ingress_duration_ms_p95": 20.0,
            },
            "matcher_only": {
                "messages": 1,
                "matchers_considered": 10,
                "matchers_selected": 4,
                "matchers_run": 3,
                "ingress_duration_ms_p95": 10.0,
            },
        },
        "runtime_stages": {
            "handler": {"samples": 1, "p95_ms": 20.0},
            "commit": {"samples": 1, "p95_ms": 2.0},
        },
        "ingress_duration_ms_p95": 20.0,
        "eligible": False,
    }


def test_bounds_named_routes_and_rolls_extra_routes_into_other() -> None:
    for index in range(65):
        record(route_modules=frozenset({f"plugin_{index:02d}"}))

    rows = metrics.route_candidate_metrics_snapshot()
    assert len(rows) == 65
    assert sum(row["messages"] for row in rows) == 65
    assert any(row["route_modules"] == [] for row in rows)


def test_ranks_matcher_work_and_marks_only_safe_single_route_eligible() -> None:
    record(route_modules=frozenset({"low"}), matchers_selected=1, matchers_run=1, duration_ms=1.0)
    record(route_modules=frozenset({"high"}), matchers_selected=5, matchers_run=4, duration_ms=5.0)
    record(route_modules=frozenset(), matchers_selected=9, matchers_run=9, duration_ms=9.0)

    rows = metrics.route_candidate_metrics_snapshot()
    assert [row["route_modules"] for row in rows] == [[], ["high"], ["low"]]
    assert rows[0]["eligible"] is False
    assert rows[1]["eligible"] is True
    assert rows[2]["eligible"] is True


def test_rolls_over_with_day_key(monkeypatch) -> None:
    monkeypatch.setattr(metrics, "today_key", lambda: "2026-08-10")
    record()
    monkeypatch.setattr(metrics, "today_key", lambda: "2026-08-11")
    assert metrics.route_candidate_metrics_snapshot() == []


def test_snapshot_has_privacy_allowlisted_fields_only() -> None:
    record(direct_outcome="direct_fallback")
    assert set(metrics.route_candidate_metrics_snapshot()[0]) == {
        "route_modules",
        "messages",
        "route_index_hits",
        "route_index_fallbacks",
        "matchers_considered",
        "matchers_selected",
        "matchers_run",
        "direct_handled",
        "direct_fallback",
        "direct_error",
        "matcher_handled",
        "direct_visible_actions",
        "direct_effect_actions",
        "outcomes",
        "runtime_stages",
        "ingress_duration_ms_p95",
        "eligible",
    }
