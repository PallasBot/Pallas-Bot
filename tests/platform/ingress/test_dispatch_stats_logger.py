from __future__ import annotations

from pallas.core.platform.ingress.dispatch_stats_logger import dispatch_stats_tick_notable


def test_dispatch_stats_tick_notable_healthy() -> None:
    snap = {
        "overload_signals": 0,
        "lane_busy": 0,
        "send_queue": {"depth": 0, "max_depth": 256, "dropped": 0},
        "ingress_duration_ms_p95": 12.0,
        "lane_wait_ms_avg": 0.0,
    }
    assert dispatch_stats_tick_notable(snap) is False


def test_dispatch_stats_tick_notable_on_overload_or_drop() -> None:
    base = {
        "overload_signals": 0,
        "lane_busy": 0,
        "send_queue": {"depth": 0, "max_depth": 256, "dropped": 0},
        "ingress_duration_ms_p95": 12.0,
        "lane_wait_ms_avg": 0.0,
    }
    assert dispatch_stats_tick_notable({**base, "overload_signals": 3}) is True
    assert dispatch_stats_tick_notable({**base, "send_queue": {"depth": 0, "max_depth": 256, "dropped": 1}}) is True
    assert dispatch_stats_tick_notable({**base, "ingress_duration_ms_p95": 2500.0}) is True
