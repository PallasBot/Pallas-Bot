from __future__ import annotations

from pallas.core.platform.ingress import dispatch_metrics


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
    dispatch_metrics.record_route_index_decision(index_hit=True, fallback=False)
    dispatch_metrics.record_route_index_decision(index_hit=False, fallback=True)
    snap = dispatch_metrics.dispatch_metrics_snapshot()
    assert snap["group_messages"] == 100
    assert snap["matchers_considered"] == 1000
    assert snap["ingress_duration_ms_p95"] == 96.0
    assert snap["matchers_selected_ratio"] == 0.4
    assert snap["route_index_hits"] == 1
    assert snap["route_index_fallbacks"] == 1
    assert snap["command_traffic"] == 50
    assert snap["route_index_hit_ratio"] == 0.02
    assert snap["route_index_fallback_ratio"] == 0.02


def test_lane_wait_and_alerts() -> None:
    dispatch_metrics.clear_dispatch_metrics_for_tests()
    dispatch_metrics.record_lane_wait(120.0)
    dispatch_metrics.record_lane_wait(0.0, busy=True)
    snap = dispatch_metrics.dispatch_metrics_snapshot()
    assert snap["lane_wait_count"] == 1
    assert snap["lane_busy"] == 1
    assert snap["lane_wait_ms_avg"] == 120.0


def test_dispatch_metrics_include_lane_capacity_snapshot() -> None:
    payload = dispatch_metrics.build_dispatch_metrics_payload(
        day_key="2026-08-06",
        counters={},
        ingress_duration_ms_p95=None,
        send_queue={},
        pool_budget={},
        pg_util=None,
        lanes={"chat": {"limit": 8, "in_use": 6}},
    )

    assert payload["lanes"] == {"chat": {"limit": 8, "in_use": 6}}


def test_dispatch_metrics_include_route_candidates(monkeypatch) -> None:
    monkeypatch.setattr(dispatch_metrics, "route_candidate_metrics_snapshot", lambda: [{"route_modules": ["help"]}])

    snap = dispatch_metrics.dispatch_metrics_snapshot()

    assert snap["route_candidates"] == [{"route_modules": ["help"]}]


def test_chatter_overload_degraded_counter() -> None:
    dispatch_metrics.clear_dispatch_metrics_for_tests()
    dispatch_metrics.record_chatter_overload_degraded()
    dispatch_metrics.record_chatter_overload_dropped()
    snap = dispatch_metrics.dispatch_metrics_snapshot()
    assert snap["chatter_overload_degraded"] == 1
    assert snap["chatter_overload_dropped"] == 1


def test_dispatch_alerts() -> None:
    assert dispatch_metrics.dispatch_alerts(p95_ms=1_000.0, pg_util=None) == []
    assert dispatch_metrics.dispatch_alerts(p95_ms=1_001.0, pg_util=None) == ["ingress_p95_over_1000ms"]
    assert dispatch_metrics.dispatch_alerts(p95_ms=5_000.0, pg_util=None) == ["ingress_p95_over_1000ms"]
    assert dispatch_metrics.dispatch_alerts(p95_ms=5_001.0, pg_util=None) == ["ingress_p95_over_5000ms"]
    assert "pg_pool_over_85pct" in dispatch_metrics.dispatch_alerts(p95_ms=None, pg_util=0.9)


def test_dispatch_metrics_include_work_aux_status_and_alerts(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.work_jobs.observability.work_aux_status",
        lambda: {"available": True, "heartbeat_age_sec": 16.0, "pending": 4, "oldest_pending_age_sec": 301.0},
    )

    snap = dispatch_metrics.dispatch_metrics_snapshot()

    assert snap["work_aux"]["pending"] == 4
    assert "work_aux_heartbeat_stale" in snap["alerts"]
    assert "work_aux_backlog_old" in snap["alerts"]


def test_dispatch_metrics_include_conversation_scheduler(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.conversation_scheduler.conversation_scheduler_status",
        lambda: {
            "enabled": True,
            "pending": 12,
            "active": 3,
            "ready": 4,
            "max_pending": 512,
            "wait_ms_p95": 84.0,
            "backpressure_waits": 2,
        },
    )

    snap = dispatch_metrics.dispatch_metrics_snapshot()

    assert snap["conversation_scheduler"]["pending"] == 12
    assert snap["conversation_scheduler"]["wait_ms_p95"] == 84.0


def test_dispatch_metrics_include_snapshot_health(monkeypatch) -> None:
    monkeypatch.setattr(
        dispatch_metrics,
        "ingress_snapshot_health",
        lambda: {
            "ban_gate": {"ready": True, "refresh_failures": 2},
            "disabled_plugins": {"ready": False, "refresh_failures": 1},
        },
    )

    snap = dispatch_metrics.dispatch_metrics_snapshot()

    assert snap["snapshot_health"]["ban_gate"]["refresh_failures"] == 2
    assert snap["snapshot_health"]["disabled_plugins"]["ready"] is False


def test_merge_snapshot_health_counts_worker_readiness() -> None:
    merged = dispatch_metrics.merge_snapshot_health([
        {
            "ban_gate": {
                "ready": True,
                "refresh_age_sec": 2.0,
                "refresh_failures": 1,
                "last_failure_age_sec": 8.0,
            }
        },
        {
            "ban_gate": {
                "ready": False,
                "refresh_age_sec": 5.0,
                "refresh_failures": 2,
                "last_failure_age_sec": 4.0,
            }
        },
    ])

    assert merged["ban_gate"] == {
        "ready": False,
        "workers": 2,
        "ready_workers": 1,
        "refresh_age_sec_max": 5.0,
        "refresh_failures": 3,
        "last_failure_age_sec_min": 4.0,
    }
