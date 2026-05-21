from __future__ import annotations

from src.common.shard.logs.errors import (
    append_shard_log_error,
    collect_cluster_log_errors_from_jsonl,
    errors_jsonl_path,
)
from src.common.shard.logs.view import dedupe_mirror_stdio_lines


def test_append_and_collect_errors(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr("src.common.shard.logs.view.shard_logs_dir", lambda: log_dir)
    monkeypatch.setattr(
        "src.common.shard.logs.errors.shard_errors_dir",
        lambda: log_dir / "errors",
    )

    append_shard_log_error(
        {
            "at": 100,
            "plugin": "worker-1/duel",
            "exc_type": "ValueError",
            "message": "boom",
            "traceback": "",
        },
        stem="worker-1",
    )
    rows = collect_cluster_log_errors_from_jsonl(limit=10)
    assert len(rows) == 1
    assert rows[0]["exc_type"] == "ValueError"
    assert errors_jsonl_path("worker-1").is_file()


def test_dedupe_mirror_stdio():
    lines = [
        "[worker-0] 05-21 12:00:00 | INFO     | src:1 - [uvicorn] hello",
        "[worker-0] 2026-05-21 12:00:00,100 - INFO - [uvicorn] hello",
        "[worker-0] 05-21 12:00:01 | ERROR    | x:1 - fail",
    ]
    out = dedupe_mirror_stdio_lines(lines)
    assert len(out) == 2
    assert "ERROR" in out[1]
