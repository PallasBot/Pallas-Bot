"""任务计数 / gates 日汇总禁止回退；worker 自愈回灌。"""

from __future__ import annotations

import json

from pallas.product.llm.llm_daily_stats_store import merge_side_snapshot
from pallas.product.llm.task_metrics import (
    clear_llm_task_metrics_for_tests,
    llm_task_metrics_snapshot,
    record_bot_llm_task,
)


def test_merge_side_snapshot_does_not_shrink_by_task_or_gates() -> None:
    existing = {
        "by_task": {"llm_chat": {"submit_ok": 50, "callback_ok": 40}},
        "totals": {"submit_ok": 50, "reply_gate_proceed": 30},
        "gates": {"skip": 5, "defer": 2, "proceed": 30},
    }
    incoming = {
        "by_task": {"llm_chat": {"submit_ok": 3, "callback_ok": 2}},
        "totals": {"submit_ok": 3, "reply_gate_proceed": 1},
        "gates": {"skip": 0, "defer": 0, "proceed": 1},
    }
    merged = merge_side_snapshot(existing, incoming)
    assert merged["by_task"]["llm_chat"]["submit_ok"] == 50
    assert merged["totals"]["submit_ok"] == 50
    assert merged["gates"]["proceed"] == 30


def test_task_metrics_worker_rehydrates(tmp_path, monkeypatch) -> None:
    clear_llm_task_metrics_for_tests()
    import pallas.product.llm.task_metrics as tm

    monkeypatch.setattr(tm, "today_key", lambda: "2026-07-27")
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_worker", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_hub", lambda: False)
    monkeypatch.setattr("pallas.core.platform.shard.context.shard_id", lambda: 2)
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.read_worker_stats_file",
        lambda shard_id: {
            "llm_task": {
                "day_key": "2026-07-27",
                "by_task": {
                    "llm_chat": {
                        "submit_ok": 9,
                        "callback_ok": 8,
                        "reply_gate_proceed": 7,
                        "route_counts": {"plain_llm_chat": 9},
                    }
                },
                "totals": {
                    "submit_ok": 9,
                    "callback_ok": 8,
                    "reply_gate_proceed": 7,
                },
            }
        },
    )
    with tm._lock:
        tm._day_key = "2026-07-27"
        tm._hydrated = False
        tm._counters.clear()

    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["submit_ok"] == 9
    assert snap["by_task"]["llm_chat"]["route_counts"]["plain_llm_chat"] == 9
    assert snap["totals"]["reply_gate_proceed"] == 7

    record_bot_llm_task("llm_chat", "submit_ok")
    snap2 = llm_task_metrics_snapshot()
    assert snap2["by_task"]["llm_chat"]["submit_ok"] == 10


def test_task_metrics_stale_file_salvaged(tmp_path, monkeypatch) -> None:
    clear_llm_task_metrics_for_tests()
    import pallas.product.llm.task_metrics as tm

    path = tmp_path / "llm_task_stats.json"
    monkeypatch.setattr(tm, "stats_file_path", lambda: path)
    monkeypatch.setattr(tm, "today_key", lambda: "2026-07-27")
    written: list[tuple] = []

    def fake_write(day: str, side: str, snapshot: dict) -> None:
        written.append((day, side, snapshot))

    monkeypatch.setattr("pallas.product.llm.llm_daily_stats_store.write_day_side", fake_write)
    path.write_text(
        json.dumps({
            "v": 1,
            "day_key": "2026-07-25",
            "by_task": {"llm_chat": {"submit_ok": 11}},
            "totals": {"submit_ok": 11},
        }),
        encoding="utf-8",
    )
    with tm._lock:
        tm._day_key = "2026-07-27"
        tm._hydrated = False
        tm._counters.clear()

    snap = llm_task_metrics_snapshot()
    assert snap["totals"].get("submit_ok", 0) == 0
    assert written
    assert written[0][0] == "2026-07-25"
    assert written[0][1] == "bot"
    assert written[0][2]["totals"]["submit_ok"] == 11
