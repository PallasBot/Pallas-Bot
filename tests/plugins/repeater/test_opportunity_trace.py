from __future__ import annotations

import concurrent.futures

from packages.repeater.opportunity_trace import (
    append_repeater_opportunity_trace,
    read_recent_repeater_opportunity_trace,
)


def test_append_and_read_repeater_opportunity_trace(tmp_path, monkeypatch) -> None:
    from packages.repeater import opportunity_trace as mod

    monkeypatch.setattr(mod, "repeater_opportunity_trace_path", lambda: tmp_path / "repeater_opportunity_trace.jsonl")

    assert append_repeater_opportunity_trace({"kind": "llm_opportunity_gate", "accepted": True, "reply_mode": "god"})
    assert append_repeater_opportunity_trace({"kind": "repeater_reply_bundle", "pick_path": "god_recent_live"})

    rows = read_recent_repeater_opportunity_trace(limit=10)
    assert len(rows) == 2
    assert rows[0]["kind"] == "llm_opportunity_gate"
    assert rows[1]["pick_path"] == "god_recent_live"


def test_append_opportunity_trace_survives_shared_tmp_race(tmp_path, monkeypatch) -> None:
    """分片多进程曾共用固定 .tmp，os.replace 会 FileNotFoundError。"""
    from packages.repeater import opportunity_trace as mod

    path = tmp_path / "repeater_opportunity_trace.jsonl"
    monkeypatch.setattr(mod, "repeater_opportunity_trace_path", lambda: path)

    def write_one(i: int) -> bool:
        return append_repeater_opportunity_trace({"kind": "race", "i": i})

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write_one, range(40)))

    assert all(results)
    rows = read_recent_repeater_opportunity_trace(limit=100)
    assert len(rows) == 40
    assert not list(tmp_path.glob("*.tmp"))
