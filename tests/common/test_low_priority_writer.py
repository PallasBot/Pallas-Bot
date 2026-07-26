"""low_priority_writer 背压与不健康暂停。"""

from __future__ import annotations

import pytest
from pallas.core.foundation.db.db_health import note_db_probe_result, reset_db_health_for_tests
from pallas.core.foundation.db.low_priority_writer import (
    LowPriorityWriter,
    reset_low_priority_writers_for_tests,
)
from pallas.core.foundation.db.schema_observability import (
    reset_schema_observability_for_tests,
    run_schema_ensure_step,
    schema_observability_snapshot,
)


@pytest.fixture(autouse=True)
async def _reset():
    reset_db_health_for_tests()
    reset_schema_observability_for_tests()
    await reset_low_priority_writers_for_tests()
    yield
    reset_db_health_for_tests()
    reset_schema_observability_for_tests()
    await reset_low_priority_writers_for_tests()


@pytest.mark.asyncio
async def test_drop_oldest_when_full():
    flushed: list[list[int]] = []

    async def flush(batch: list[object]) -> None:
        flushed.append([int(x) for x in batch])

    writer = LowPriorityWriter(name="t", flush_batch=flush, max_retain=3, batch_size=10, flush_interval_sec=30)
    for i in range(5):
        writer.enqueue(i)
    assert writer.dropped == 2
    assert list(writer.buffer) == [2, 3, 4]
    await writer._flush_once()
    assert flushed == [[2, 3, 4]]
    assert writer.flushed == 3


@pytest.mark.asyncio
async def test_skip_flush_when_unhealthy():
    flushed: list[list[int]] = []

    async def flush(batch: list[object]) -> None:
        flushed.append([int(x) for x in batch])

    writer = LowPriorityWriter(name="t2", flush_batch=flush, max_retain=8, batch_size=8)
    writer.enqueue(1)
    note_db_probe_result(False, reason="x")
    note_db_probe_result(False, reason="x")
    await writer._flush_once()
    assert flushed == []
    assert list(writer.buffer) == [1]


def test_schema_ensure_counts_ok_and_fail():
    def _bad(_c: object) -> None:
        raise RuntimeError("boom")

    run_schema_ensure_step("ok_step", lambda _c: None, connection=None)
    with pytest.raises(RuntimeError, match="boom"):
        run_schema_ensure_step("bad_step", _bad, connection=None)
    snap = schema_observability_snapshot()
    assert snap["ok"] == 1
    assert snap["failed"] == 1
    assert "bad_step" in snap["last_error"]
