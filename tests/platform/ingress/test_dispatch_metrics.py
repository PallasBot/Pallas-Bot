from __future__ import annotations

from src.platform.ingress import dispatch_metrics


def test_record_group_message_and_p95() -> None:
    dispatch_metrics.clear_dispatch_metrics_for_tests()
    for ms in range(1, 101):
        dispatch_metrics.record_group_message_ingress(
            duration_ms=float(ms),
            command_traffic=ms % 2 == 0,
            matchers_considered=10,
            matchers_selected=4,
            matchers_run=3,
        )
    snap = dispatch_metrics.dispatch_metrics_snapshot()
    assert snap["group_messages"] == 100
    assert snap["matchers_considered"] == 1000
    assert snap["ingress_duration_ms_p95"] == 96.0
    assert snap["matchers_selected_ratio"] == 0.4


def test_lane_wait_and_alerts() -> None:
    dispatch_metrics.clear_dispatch_metrics_for_tests()
    dispatch_metrics.record_lane_wait(120.0)
    dispatch_metrics.record_lane_wait(0.0, busy=True)
    snap = dispatch_metrics.dispatch_metrics_snapshot()
    assert snap["lane_wait_count"] == 1
    assert snap["lane_busy"] == 1
    assert snap["lane_wait_ms_avg"] == 120.0


def test_dispatch_alerts() -> None:
    alerts = dispatch_metrics.dispatch_alerts(p95_ms=150.0, pg_util=0.9)
    assert "ingress_p95_over_100ms" in alerts
    assert "pg_pool_over_85pct" in alerts
