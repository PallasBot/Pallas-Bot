from __future__ import annotations

from pathlib import Path

from src.console.cli.runtime_mode import pid_alive, read_pid_file, resolve_bot_mode


def test_read_pid_file_missing(tmp_path: Path):
    assert read_pid_file(tmp_path / "missing.pid") is None


def test_pid_alive_zero():
    assert pid_alive(0) is False


def test_resolve_bot_mode_explicit():
    assert resolve_bot_mode("unified") == "unified"
    assert resolve_bot_mode("shard") == "shard"
