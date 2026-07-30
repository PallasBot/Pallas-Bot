from __future__ import annotations

from pallas.core.platform.ingress import dispatch_metrics, hotpath_metrics


def test_hotpath_bundle_and_route_samples() -> None:
    hotpath_metrics.clear_hotpath_metrics_for_tests()
    hotpath_metrics.record_route_resolve_ms(0.4)
    hotpath_metrics.record_route_resolve_ms(1.2)
    hotpath_metrics.record_keywords_extract_ms(3.0)
    hotpath_metrics.record_bundle_lookup(duration_ms=5.0, cache_hit=True, found=True)
    hotpath_metrics.record_bundle_lookup(duration_ms=1.0, cache_hit=True, found=False, negative_hit=True)
    hotpath_metrics.record_bundle_lookup(duration_ms=40.0, cache_hit=False, found=True)
    hotpath_metrics.record_bundle_lookup(duration_ms=900.0, cache_hit=False, error="timeout")
    hotpath_metrics.record_learn_skipped_pressure()
    hotpath_metrics.record_chat_shed_sidework()

    snap = hotpath_metrics.hotpath_metrics_snapshot()
    assert snap["route_resolve_calls"] == 2
    assert snap["bundle_cache_hit"] == 1
    assert snap["bundle_cache_negative_hit"] == 1
    assert snap["bundle_cache_miss"] == 2
    assert snap["bundle_timeout"] == 1
    assert snap["bundle_found"] == 2
    assert snap["learn_skipped_pressure"] == 1
    assert snap["chat_shed_sidework"] == 1
    assert snap["bundle_cache_hit_ratio"] == round(2 / 4, 4)
    assert snap["route_ms_p95"] is not None
    assert snap["bundle_ms_p95"] is not None


def test_hotpath_bundle_stages_and_sql() -> None:
    hotpath_metrics.clear_hotpath_metrics_for_tests()
    hotpath_metrics.record_bundle_stages(outcome="db_miss", db_find_ms=12.0)
    hotpath_metrics.record_bundle_stages(
        outcome="found",
        db_find_ms=80.0,
        persona_ms=5.0,
        affect_ms=2.0,
        ban_ms=1.0,
        feedback_ms=3.0,
        select_ms=4.0,
    )
    hotpath_metrics.record_bundle_stages(
        outcome="no_candidates",
        db_find_ms=90.0,
        persona_ms=6.0,
        affect_ms=2.5,
        ban_ms=1.5,
        feedback_ms=0.5,
        select_ms=1.0,
    )
    hotpath_metrics.record_reply_snapshot(hit=True)
    hotpath_metrics.record_reply_snapshot(hit=False)
    hotpath_metrics.record_reply_snapshot(hit=False, skipped=True)
    hotpath_metrics.record_reply_query_stages(
        context_ms=10.0,
        ban_ms=1.0,
        answer_ms=20.0,
        message_ms=30.0,
        total_ms=61.0,
    )

    snap = hotpath_metrics.hotpath_metrics_snapshot()
    assert snap["bundle_stage_db_miss"] == 1
    assert snap["bundle_stage_db_hit"] == 2
    assert snap["bundle_stage_found"] == 1
    assert snap["bundle_stage_no_candidates"] == 1
    assert snap["reply_snapshot_hit"] == 1
    assert snap["reply_snapshot_miss"] == 1
    assert snap["reply_snapshot_skip"] == 1
    assert snap["reply_snapshot_hit_ratio"] == 0.5
    assert snap["reply_query_uncached"] == 1
    assert snap["db_find_ms_p95"] is not None
    assert snap["persona_ms_p95"] is not None
    assert snap["sql_total_ms_p95"] == 61.0
    assert snap["sql_message_ms_p95"] == 30.0

    merged = hotpath_metrics.merge_hotpath_metrics([snap, snap])
    assert merged["bundle_stage_db_miss"] == 2
    assert merged["reply_query_uncached"] == 2
    assert merged["db_find_ms_p95"] == snap["db_find_ms_p95"]


def test_dispatch_snapshot_includes_hotpath() -> None:
    dispatch_metrics.clear_dispatch_metrics_for_tests()
    hotpath_metrics.clear_hotpath_metrics_for_tests()
    hotpath_metrics.record_route_resolve_ms(0.5)
    snap = dispatch_metrics.dispatch_metrics_snapshot()
    assert "hotpath" in snap
    assert snap["hotpath"]["route_resolve_calls"] == 1
