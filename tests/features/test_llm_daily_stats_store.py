from __future__ import annotations

from pallas.product.llm import llm_daily_stats_store


def test_merge_side_snapshot_keeps_token_payload() -> None:
    merged = llm_daily_stats_store.merge_side_snapshot(
        None,
        {
            "source": "ai",
            "day_key": "2026-06-18",
            "tokens": {
                "prompt_tokens": 120,
                "completion_tokens": 45,
                "total_tokens": 165,
            },
            "totals": {"task_ok": 3},
            "reachable": True,
        },
    )

    assert merged["tokens"]["prompt_tokens"] == 120
    assert merged["tokens"]["completion_tokens"] == 45
    assert merged["tokens"]["total_tokens"] == 165
    assert merged["totals"]["task_ok"] == 3


def test_load_range_returns_token_history(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        llm_daily_stats_store,
        "stats_file_path",
        lambda: tmp_path / "llm_daily_stats.json",
    )

    llm_daily_stats_store.write_day_side(
        "2026-06-18",
        "ai",
        {
            "source": "ai",
            "day_key": "2026-06-18",
            "tokens": {
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
            },
            "totals": {"task_ok": 8},
            "reachable": True,
        },
    )

    rows, start, end = llm_daily_stats_store.load_range(
        start_day="2026-06-18",
        end_day="2026-06-18",
    )

    assert start == "2026-06-18"
    assert end == "2026-06-18"
    assert len(rows) == 1
    assert rows[0]["ai"]["tokens"]["prompt_tokens"] == 200
    assert rows[0]["ai"]["tokens"]["completion_tokens"] == 100
    assert rows[0]["ai"]["tokens"]["total_tokens"] == 300
