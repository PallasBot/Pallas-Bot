from __future__ import annotations

from pallas.core.foundation.db.pg_activity_diagnostics import (
    PgActivitySnapshot,
    classify_pg_bottleneck,
    format_pg_activity_detail,
    should_emit_pg_activity_detail,
    wait_summary,
)


def test_wait_summary_skips_none():
    snap = PgActivitySnapshot(wait_breakdown=[("none", "-", 40), ("Lock", "relation", 2), ("IO", "DataFileRead", 1)])
    assert wait_summary(snap) == "Lock/relation:2|IO/DataFileRead:1"


def test_classify_lock_contention_from_blockers():
    snap = PgActivitySnapshot(
        blockers=[{"blocked_pid": 1, "blocking_pid": 2}],
        slow_active=[{"query_sec": 5.0, "wait_event_type": None, "wait_event": None}],
    )
    assert classify_pg_bottleneck(snap) == "lock_contention"


def test_classify_io_wait():
    snap = PgActivitySnapshot(
        wait_breakdown=[("IO", "DataFileRead", 3), ("LWLock", "BufferContent", 2)],
    )
    assert classify_pg_bottleneck(snap) == "io_wait"


def test_classify_slow_query_when_active_not_waiting():
    snap = PgActivitySnapshot(
        slow_active=[
            {
                "pid": 10,
                "query_sec": 8.5,
                "wait_event_type": None,
                "wait_event": None,
                "query_preview": "SELECT 1",
            }
        ]
    )
    assert classify_pg_bottleneck(snap) == "slow_query"


def test_should_emit_auto_on_pressure(monkeypatch):
    monkeypatch.setattr("pallas.core.foundation.db.pg_activity_diagnostics.pg_activity_diag_mode", lambda: "auto")
    monkeypatch.setattr("pallas.core.foundation.db.pg_activity_diagnostics.pg_activity_diag_always", lambda: False)
    snap = PgActivitySnapshot()
    assert should_emit_pg_activity_detail(
        snap,
        under_pressure=True,
        idle_in_tx_count=0,
        slow_sessions=0,
        slow_max_ms=0.0,
    )


def test_should_emit_off(monkeypatch):
    snap = PgActivitySnapshot(blockers=[{"blocked_pid": 1}])
    monkeypatch.setattr("pallas.core.foundation.db.pg_activity_diagnostics.pg_activity_diag_mode", lambda: "off")
    assert not should_emit_pg_activity_detail(
        snap,
        under_pressure=True,
        idle_in_tx_count=3,
        slow_sessions=9,
        slow_max_ms=9999.0,
    )


def test_format_detail_includes_bottleneck_and_blocker():
    snap = PgActivitySnapshot(
        state_counts={"active": 2, "idle": 30},
        wait_breakdown=[("Lock", "relation", 1)],
        blockers=[
            {
                "blocked_pid": 11,
                "blocking_pid": 22,
                "blocked_wait_type": "Lock",
                "blocked_wait": "relation",
                "blocked_sec": 3.2,
                "blocked_query": "UPDATE context",
                "blocking_sec": 10.1,
                "blocking_query": "SELECT big",
            }
        ],
        slow_active=[
            {
                "pid": 11,
                "query_sec": 3.2,
                "wait_event_type": "Lock",
                "wait_event": "relation",
                "query_preview": "UPDATE context",
            }
        ],
    )
    text = format_pg_activity_detail(snap)
    assert "bottleneck=lock_contention" in text
    assert "block: blocked_pid=11" in text
    assert "slow_active: pid=11" in text
