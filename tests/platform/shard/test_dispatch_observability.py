from __future__ import annotations

from pallas.core.platform.ingress import dispatch_metrics


def test_merge_dispatch_metrics_sums_counters() -> None:
    rows = [
        {
            "day_key": "2026-06-15",
            "group_messages": 10,
            "matchers_considered": 100,
            "matchers_selected": 40,
            "matchers_run": 30,
            "lane_wait_ms_total": 200,
            "lane_wait_count": 2,
            "ingress_duration_ms_p95": 80.0,
            "send_queue": {"depth_live": 1, "max_depth": 256, "sent": 5, "dropped": 0, "workers": 2},
            "pool_budget": {"capacity": 10, "checked_out": 3, "utilization": 0.3},
        },
        {
            "day_key": "2026-06-15",
            "group_messages": 5,
            "matchers_considered": 50,
            "matchers_selected": 10,
            "matchers_run": 8,
            "lane_wait_ms_total": 100,
            "lane_wait_count": 1,
            "ingress_duration_ms_p95": 120.0,
            "send_queue": {"depth_live": 2, "max_depth": 256, "sent": 3, "dropped": 1, "workers": 2},
            "pool_budget": {"capacity": 10, "checked_out": 8, "utilization": 0.8},
        },
    ]
    merged = dispatch_metrics.merge_dispatch_metrics(rows)
    assert merged["group_messages"] == 15
    assert merged["matchers_considered"] == 150
    assert merged["ingress_duration_ms_p95"] == 120.0
    assert merged["lane_wait_ms_avg"] == 100.0
    assert merged["send_queue"]["depth_live"] == 3
    assert merged["send_queue"]["sent"] == 8
    assert merged["pool_budget"]["utilization"] == 0.8
    assert "ingress_p95_over_100ms" in merged["alerts"]


def test_aggregate_ingress_dispatch_unified(monkeypatch) -> None:
    from pallas.core.platform.shard import dispatch_observability

    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: False)
    dispatch_metrics.clear_dispatch_metrics_for_tests()
    dispatch_metrics.record_group_message_ingress(
        duration_ms=10.0,
        command_traffic=True,
        matchers_considered=5,
        matchers_selected=2,
        matchers_run=1,
    )
    data = dispatch_observability.aggregate_ingress_dispatch()
    assert data["sharded"] is False
    assert data["workers"] == []
    assert data["group_messages"] == 1
