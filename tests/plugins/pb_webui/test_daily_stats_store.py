from __future__ import annotations

from typing import Any

from packages.pb_webui import daily_stats_store


def test_write_day_and_load_range(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_stats_store, "stats_file_path", lambda: tmp_path / "console_daily_stats.json")
    daily_stats_store.write_day_totals("2026-05-10", "111", 1, 2, 3)
    daily_stats_store.write_day_totals("2026-05-11", "111", 4, 5, 6)
    rows, start, end = daily_stats_store.load_range(
        self_id=None,
        start_day="2026-05-01",
        end_day="2026-05-15",
    )
    assert start == "2026-05-01"
    assert end == "2026-05-15"
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-05-10"
    assert rows[0]["received"] == 1
    assert rows[0]["sent"] == 2
    assert rows[0]["matcher_runs"] == 3
    assert rows[1]["matcher_runs"] == 6


def test_load_range_filter_self_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_stats_store, "stats_file_path", lambda: tmp_path / "console_daily_stats.json")
    daily_stats_store.write_day_totals("2026-05-10", "222", 9, 0, 1)
    daily_stats_store.write_day_totals("2026-05-10", "333", 0, 0, 0)
    rows, _, _ = daily_stats_store.load_range(
        self_id="222",
        start_day="2026-05-10",
        end_day="2026-05-10",
    )
    assert len(rows) == 1
    assert rows[0]["self_id"] == "222"


def test_merge_today_row_keeps_disk_when_live_zero() -> None:
    by_key: dict[tuple[str, str], dict[str, Any]] = {
        ("2026-05-23", "111"): {
            "date": "2026-05-23",
            "self_id": "111",
            "received": 100,
            "sent": 2,
            "matcher_runs": 50,
        },
    }
    daily_stats_store.merge_today_row(
        by_key,
        day="2026-05-23",
        self_id="111",
        received=0,
        sent=0,
        matcher_runs=0,
    )
    row = by_key[("2026-05-23", "111")]
    assert row["received"] == 100
    assert row["matcher_runs"] == 50


def test_merge_today_row_overwrites_with_live() -> None:
    by_key: dict[tuple[str, str], dict[str, Any]] = {
        ("2026-05-23", "111"): {
            "date": "2026-05-23",
            "self_id": "111",
            "received": 1,
            "sent": 0,
            "matcher_runs": 1,
        },
    }
    daily_stats_store.merge_today_row(
        by_key,
        day="2026-05-23",
        self_id="111",
        received=9,
        sent=3,
        matcher_runs=7,
    )
    row = by_key[("2026-05-23", "111")]
    assert row["received"] == 9
    assert row["sent"] == 3
    assert row["matcher_runs"] == 7


def test_atomic_write_uses_process_scoped_tmp(monkeypatch, tmp_path) -> None:
    target = tmp_path / "console_daily_stats.json"
    monkeypatch.setattr(daily_stats_store, "stats_file_path", lambda: target)
    pids = iter([111, 222])
    monkeypatch.setattr(daily_stats_store.os, "getpid", lambda: next(pids))
    daily_stats_store._atomic_write({"v": 1, "by_day": {}})
    daily_stats_store._atomic_write({"v": 1, "by_day": {"2026-05-23": {}}})
    assert target.is_file()
    assert not list(tmp_path.glob("console_daily_stats.*.tmp"))


def test_write_batch_day_totals_merges_same_day(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_stats_store, "stats_file_path", lambda: tmp_path / "console_daily_stats.json")
    daily_stats_store.write_batch_day_totals([
        ("2026-05-23", "111", 10, 2, 5),
        ("2026-05-23", "111", 8, 1, 7),
    ])
    rows, _, _ = daily_stats_store.load_range(
        self_id="111",
        start_day="2026-05-23",
        end_day="2026-05-23",
    )
    assert len(rows) == 1
    assert rows[0]["received"] == 10
    assert rows[0]["sent"] == 2
    assert rows[0]["matcher_runs"] == 7


def test_write_batch_keeps_disk_when_live_zero(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_stats_store, "stats_file_path", lambda: tmp_path / "console_daily_stats.json")
    daily_stats_store.write_day_totals("2026-05-23", "111", 100, 2, 50)
    daily_stats_store.write_batch_day_totals([("2026-05-23", "111", 0, 0, 0)])
    rows, _, _ = daily_stats_store.load_range(
        self_id="111",
        start_day="2026-05-23",
        end_day="2026-05-23",
    )
    assert rows[0]["received"] == 100
    assert rows[0]["matcher_runs"] == 50


def test_merge_day_bot_record_prefers_higher_counts() -> None:
    merged = daily_stats_store.merge_day_bot_record(
        {"received": 5, "sent": 1, "matcher_runs": 3},
        9,
        0,
        2,
    )
    assert merged == {"received": 9, "sent": 1, "matcher_runs": 3, "api_calls": 0}
