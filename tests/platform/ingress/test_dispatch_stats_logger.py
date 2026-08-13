from __future__ import annotations

from pallas.core.platform.ingress.dispatch_stats_logger import (
    _dispatch_stats_text,
    dispatch_stats_tick_notable,
)
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


def test_dispatch_stats_text_groups_sections_with_header() -> None:
    snap = {
        "group_messages": 753,
        "command_traffic": 4,
        "chatter_traffic": 749,
        "route_index_hits": 4,
        "route_index_fallbacks": 0,
        "matchers_considered": 20574,
        "matchers_selected": 3135,
        "matchers_run": 3131,
        "ingress_duration_ms_p95": 7614.81,
        "lane_wait_ms_avg": 5.74,
        "overload_signals": 8509,
        "chatter_overload_dropped": 0,
        "chatter_overload_degraded": 606,
        "stale_messages_dropped": 0,
        "lane_busy": 194,
        "lanes": {"chat": {"in_use": 0, "limit": 8}},
        "conversation_scheduler": {
            "pending": 0,
            "max_pending": 1024,
            "active": 0,
            "ready": 0,
            "llm_active": 0,
            "llm_waiting": 0,
            "llm_reserved": 6,
            "wait_ms_p95": 131.14,
            "backpressure_waits": 0,
        },
        "send_queue": {"depth": 0, "max_depth": 256, "dropped": 0},
        "hotpath": {
            "route_ms_p95": 0.016,
            "keywords_ms_p95": 0.104,
            "bundle_ms_p95": 182.332,
            "bundle_cache_hit_ratio": 0.0172,
            "db_find_ms_p95": 142.211,
            "persona_ms_p95": 20.43,
            "ban_ms_p95": 0.087,
            "feedback_ms_p95": 13.385,
            "select_ms_p95": 15.495,
            "sql_total_ms_p95": 107.898,
            "reply_snapshot_hit_ratio": 0.0,
            "learn_buffered": 97,
            "learn_persisted": 97,
            "learn_skipped_full": 0,
            "learn_dropped_shutdown": 0,
            "chat_shed_sidework": 0,
            "llm_retained_under_shed": 0,
            "llm_budget_skipped_explicit": 0,
            "llm_budget_skipped_ambient": 0,
            "llm_budget_skipped_repeater_strong": 0,
            "llm_budget_skipped_repeater_weak": 0,
            "llm_budget_skipped_proactive": 0,
        },
        "work_aux": {
            "completed_since_start": 258,
            "retried_since_start": 5,
            "dead_lettered_since_start": 0,
        },
    }

    text = _dispatch_stats_text(snap)

    lines = text.splitlines()
    assert len(lines) == 4
    assert lines[0] == "ingress_dispatch: processed [753] group messages ([4] commands, [749] chat)"
    assert lines[1] == "  p95 [7614.81ms]  full [-]  overload [8509]  degraded [606]"
    assert lines[2] == "  scheduler [0/1024]  llm [0/0/6]  send_q [0/256]"
    assert lines[3] == "  bundle [182.332ms]  db_find [142.211ms]  sql [107.898ms]"


def test_dispatch_stats_text_omits_missing_ms_values() -> None:
    text = _dispatch_stats_text({"group_messages": 1})
    assert "p95 [-]" in text
    assert "bundle [-]" in text
