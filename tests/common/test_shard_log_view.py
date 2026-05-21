from __future__ import annotations

from pathlib import Path

from src.common.shard.logs.view import (
    collect_cluster_log_errors,
    list_shard_log_sources,
    merge_cluster_log_lines,
    prefix_log_source,
    tail_log_file,
)


def test_prefix_log_source():
    line = "05-21 12:00:00 | INFO     | src:1 - hello"
    out = prefix_log_source(line, "worker-1")
    assert "[worker-1]" in out
    assert "hello" in out


def test_merge_cluster_sorts_and_limits(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-0.log").write_text(
        "05-21 10:00:00 | INFO     | a:1 - early worker\n"
        "05-21 12:00:00 | INFO     | a:1 - late worker\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.common.shard.logs.view.shard_logs_dir", lambda: log_dir)

    hub = [
        "05-21 11:00:00 | INFO     | hub:1 - mid hub",
    ]
    merged = merge_cluster_log_lines(10, "all", hub_ring_lines=hub)
    assert len(merged) == 3
    assert any("[hub]" in row for row in merged)
    assert merged[-1].endswith("late worker") or "late worker" in merged[-1]


def test_tail_log_file():
    p = Path(__file__)
    lines = tail_log_file(p, 5)
    assert len(lines) >= 1


def test_worker_glob_excludes_bootstrap(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-1.log").write_text(
        "05-21 12:00:00 | INFO     | a:1 - main\n",
        encoding="utf-8",
    )
    (log_dir / "worker-1.bootstrap.log").write_text(
        "asyncio.exceptions.CancelledError: x\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.common.shard.logs.view.shard_logs_dir", lambda: log_dir)
    merged = merge_cluster_log_lines(20, "all", hub_ring_lines=[])
    assert any("main" in row for row in merged)
    assert not any("CancelledError" in row for row in merged)


def test_collect_cluster_log_errors(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "worker-2.log").write_text(
        "2026-05-21 10:00:01,0 - ERROR - boom worker\n"
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1, in <module>\n"
        "ValueError: bad\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.common.shard.logs.view.shard_logs_dir", lambda: log_dir)
    rows = collect_cluster_log_errors(per_file=50, limit=10)
    assert len(rows) >= 1
    assert any("worker-2" in str(r.get("plugin")) for r in rows)
    assert any(r.get("exc_type") == "ValueError" for r in rows)
