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


def test_dispatch_snapshot_includes_hotpath() -> None:
    dispatch_metrics.clear_dispatch_metrics_for_tests()
    hotpath_metrics.clear_hotpath_metrics_for_tests()
    hotpath_metrics.record_route_resolve_ms(0.5)
    snap = dispatch_metrics.dispatch_metrics_snapshot()
    assert "hotpath" in snap
    assert snap["hotpath"]["route_resolve_calls"] == 1
