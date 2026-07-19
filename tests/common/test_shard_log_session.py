from __future__ import annotations

import os

from pallas.core.platform.shard.logs.errors import errors_jsonl_path
from pallas.core.platform.shard.logs.session import (
    maybe_rotate_logs_for_new_session,
    prune_stem_archives,
    shard_log_archive_dir,
)
from pallas.core.platform.shard.logs.view import merge_cluster_log_lines


def test_rotate_creates_fresh_main_log(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    def logs_dir():
        return log_dir

    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", logs_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.session.shard_logs_dir", logs_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.errors.shard_logs_dir", logs_dir)

    main = log_dir / "worker-0.log"
    main.write_text("05-21 10:00:00 | INFO     | a:1 - old session\n", encoding="utf-8")
    err = errors_jsonl_path("worker-0")
    err.parent.mkdir(parents=True, exist_ok=True)
    err.write_text('{"message":"old err"}\n', encoding="utf-8")
    monkeypatch.setenv("PALLAS_SHARD_LOG_ROTATE_ON_START", "true")
    monkeypatch.setenv("PALLAS_SHARD_LOG_ARCHIVE_MAX", "3")

    archived = maybe_rotate_logs_for_new_session(stem="worker-0", main_log_path=main)
    assert archived
    assert not main.exists()
    archive = shard_log_archive_dir()
    assert any(p.name.startswith("worker-0-") and p.name.endswith(".log") for p in archive.iterdir())
    assert any(p.name.endswith(".jsonl") for p in archive.iterdir())

    main.write_text("05-21 12:00:00 | INFO     | a:1 - new session\n", encoding="utf-8")
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    merged = merge_cluster_log_lines(10, "all", hub_ring_lines=[])
    assert any("new session" in row for row in merged)
    assert not any("old session" in row for row in merged)


def test_rotate_skipped_when_disabled(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    main = log_dir / "worker-1.log"
    main.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr("pallas.core.platform.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr("pallas.core.platform.shard.logs.session.shard_logs_dir", lambda: log_dir)
    monkeypatch.setenv("PALLAS_SHARD_LOG_ROTATE_ON_START", "false")

    archived = maybe_rotate_logs_for_new_session(stem="worker-1", main_log_path=main)
    assert archived == []
    assert main.read_text(encoding="utf-8") == "old\n"


def test_prune_stem_archives(tmp_path, monkeypatch):
    archive = tmp_path / "logs" / "archive"
    archive.mkdir(parents=True)
    for i in range(5):
        p = archive / f"worker-2-2026010{i}-p1.log"
        p.write_text(f"v{i}\n", encoding="utf-8")
        os.utime(p, (i + 1, i + 1))
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("pallas.core.platform.shard.logs.session.shard_logs_dir", lambda: log_dir)
    removed = prune_stem_archives(stem="worker-2", max_files=2)
    assert len(removed) == 3
    remaining = list(archive.glob("worker-2-*.log"))
    assert len(remaining) == 2
