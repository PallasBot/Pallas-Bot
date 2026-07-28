from __future__ import annotations

from pallas.core.platform.ingress.dispatch_stats_logger import dispatch_stats_tick_notable
from pallas.core.platform.ingress.message_load import reset_message_load_for_tests, signal_overload


def _base(**overrides):
    snap = {
        "overload_signals": 0,
        "lane_busy": 0,
        "send_queue": {"depth": 0, "max_depth": 256, "dropped": 0},
        "ingress_duration_ms_p95": 12.0,
        "lane_wait_ms_avg": 0.0,
    }
    snap.update(overrides)
    return snap


def test_dispatch_stats_tick_notable_healthy() -> None:
    reset_message_load_for_tests()
    assert dispatch_stats_tick_notable(_base()) is False


def test_dispatch_stats_tick_notable_ignores_overload_state_and_counter() -> None:
    reset_message_load_for_tests()
    signal_overload(0.5)
    prev = _base(overload_signals=100, lane_busy=5, send_queue={"depth": 0, "max_depth": 256, "dropped": 2})
    snap = _base(overload_signals=120, lane_busy=5, send_queue={"depth": 0, "max_depth": 256, "dropped": 2})
    assert dispatch_stats_tick_notable(snap, prev=prev) is False


def test_dispatch_stats_tick_notable_on_busy_drop_or_period_p95() -> None:
    reset_message_load_for_tests()
    prev = _base(lane_busy=1)
    assert dispatch_stats_tick_notable(_base(lane_busy=4), prev=prev) is True
    assert (
        dispatch_stats_tick_notable(
            _base(send_queue={"depth": 0, "max_depth": 256, "dropped": 1}),
            prev=_base(),
        )
        is True
    )
    assert (
        dispatch_stats_tick_notable(
            _base(group_messages=2, ingress_duration_ms_p95=2500.0),
            prev=_base(group_messages=2),
        )
        is False
    )
    assert (
        dispatch_stats_tick_notable(
            _base(group_messages=3, ingress_duration_ms_p95=2500.0),
            prev=_base(group_messages=2),
        )
        is True
    )
