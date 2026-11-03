from __future__ import annotations

import pytest

from pallas.core.foundation.db import pg_activity_diagnostics as diagnostics
from pallas.core.foundation.db.pg_activity_diagnostics import (
    PgActivitySnapshot,
    classify_pg_bottleneck,
    format_pg_activity_detail,
    should_emit_pg_activity_detail,
    wait_summary,
)


class _Result:
    def __init__(self, rows=(), scalar=None):
        self._rows = rows
        self._scalar = scalar

    def all(self):
        return self._rows

    def mappings(self):
        return self

    def scalar_one(self):
        return self._scalar


class _Connection:
    def __init__(self, engine):
        self.engine = engine

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return None

    async def execute(self, statement, _params=None):
        sql = str(statement)
        self.engine.sql.append(sql)
        if "to_regclass" in sql:
            available = next(self.engine.availability)
            if isinstance(available, Exception):
                raise available
            return _Result(scalar=available)
        if "FROM pg_stat_statements" in sql:
            return _Result(
                rows=[
                    {
                        "query_preview": "SELECT 1",
                        "calls": 3,
                        "mean_ms": 1.2,
                        "total_ms": 3.6,
                    }
                ]
            )
        if "GROUP BY state" in sql:
            return _Result(rows=[("active", 2)])
        if "GROUP BY wait_event_type, wait_event" in sql:
            return _Result(rows=[("Lock", "relation", 1)])
        if "blocked_activity.pid AS blocked_pid" in sql:
            return _Result(
                rows=[
                    {
                        "blocked_pid": 7,
                        "blocking_pid": 8,
                        "blocked_wait_type": "Lock",
                        "blocked_wait": "relation",
                        "blocked_sec": 1.0,
                        "blocked_query": "UPDATE test",
                        "blocking_sec": 2.0,
                        "blocking_query": "SELECT test",
                    }
                ]
            )
        if "AND state = 'active'" in sql:
            return _Result(
                rows=[
                    {
                        "pid": 9,
                        "query_sec": 3.0,
                        "wait_event_type": None,
                        "wait_event": None,
                        "query_preview": "SELECT active",
                    }
                ]
            )
        if "AND state = 'idle in transaction'" in sql:
            return _Result(rows=[{"pid": 10, "idle_sec": 4.0, "query_preview": "SELECT idle"}])
        return _Result()


class _Engine:
    def __init__(self, availability):
        self.availability = iter(availability)
        self.sql = []

    def connect(self):
        return _Connection(self)


def _use_fake_pg(monkeypatch, engine):
    monkeypatch.setattr("pallas.core.foundation.db.repository_pg.is_pg_initialized", lambda: True)
    monkeypatch.setattr("pallas.core.foundation.db.repository_pg.pg_engine", lambda: engine)


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


@pytest.mark.asyncio
async def test_collect_skips_statements_query_when_view_is_unavailable(monkeypatch):
    engine = _Engine([False])
    _use_fake_pg(monkeypatch, engine)

    snapshot = await diagnostics.collect_pg_activity_snapshot()

    assert snapshot.state_counts == {"active": 2}
    assert snapshot.wait_breakdown == [("Lock", "relation", 1)]
    assert not snapshot.statements_available
    assert not any("FROM pg_stat_statements" in sql for sql in engine.sql)
    assert "stat_top_mean: pg_stat_statements unavailable" in diagnostics.format_pg_activity_detail(snapshot)
    availability_sql = next(sql for sql in engine.sql if "to_regclass" in sql)
    assert "to_regclass('pg_stat_statements')" in availability_sql


@pytest.mark.asyncio
async def test_collect_reads_statements_when_view_is_available(monkeypatch):
    engine = _Engine([True])
    _use_fake_pg(monkeypatch, engine)

    snapshot = await diagnostics.collect_pg_activity_snapshot()

    assert snapshot.statements_available
    assert snapshot.statements_top == [{"query_preview": "SELECT 1", "calls": 3, "mean_ms": 1.2, "total_ms": 3.6}]
    availability_sql = next(sql for sql in engine.sql if "to_regclass" in sql)
    statements_sql = next(sql for sql in engine.sql if "FROM pg_stat_statements" in sql)
    assert "to_regclass('pg_stat_statements')" in availability_sql
    assert "FROM pg_stat_statements" in statements_sql


@pytest.mark.asyncio
async def test_collect_recovers_after_availability_check_failure(monkeypatch):
    engine = _Engine([PermissionError("catalog access denied"), True])
    _use_fake_pg(monkeypatch, engine)

    first = await diagnostics.collect_pg_activity_snapshot()
    second = await diagnostics.collect_pg_activity_snapshot()

    assert first.state_counts == {"active": 2}
    assert first.wait_breakdown == [("Lock", "relation", 1)]
    assert first.blockers[0]["blocked_pid"] == 7
    assert first.slow_active[0]["pid"] == 9
    assert first.idle_in_tx == [{"pid": 10, "idle_sec": 4.0, "query_preview": "SELECT idle"}]
    assert not first.statements_available
    assert first.error is None
    assert sum("FROM pg_stat_statements" in sql for sql in engine.sql) == 1
    assert second.statements_available
    assert second.statements_top[0]["query_preview"] == "SELECT 1"
    assert sum("to_regclass" in sql for sql in engine.sql) == 2
