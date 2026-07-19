from __future__ import annotations

from pallas.console.web.bot_web import replay_log_entries_after


def test_replay_log_entries_after_filters_by_id(monkeypatch) -> None:
    from pallas.console.web import bot_web

    monkeypatch.setattr(
        bot_web,
        "_entry_ring",
        [
            {"id": 1, "message": "a", "scope": "hub", "time": "2026-01-01 00:00:00"},
            {"id": 2, "message": "b", "scope": "hub", "time": "2026-01-01 00:00:01"},
            {"id": 3, "message": "c", "scope": "hub", "time": "2026-01-01 00:00:02"},
        ],
    )
    rows = replay_log_entries_after(1, "all")
    assert [row["id"] for row in rows] == [2, 3]
