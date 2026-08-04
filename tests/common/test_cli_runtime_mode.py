from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.console.cli import runtime_mode
from pallas.console.cli.runtime_mode import pid_alive, read_pid_file, resolve_bot_mode

if TYPE_CHECKING:
    from pathlib import Path


def test_read_pid_file_missing(tmp_path: Path):
    assert read_pid_file(tmp_path / "missing.pid") is None


def test_pid_alive_zero():
    assert pid_alive(0) is False


def test_resolve_bot_mode_explicit():
    assert resolve_bot_mode("unified") == "unified"
    assert resolve_bot_mode("shard") == "shard"


def test_runtime_instance_summary_hides_shard_roles(monkeypatch, tmp_path: Path):
    unified_pid = tmp_path / "unified.pid"
    hub_pid = tmp_path / "hub.pid"
    shard_run = tmp_path / "shard"
    worker_zero = shard_run / "worker-0.pid"
    worker_one = shard_run / "worker-1.pid"
    for path, pid in ((unified_pid, 101), (hub_pid, 201), (worker_zero, 202), (worker_one, 203)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pid), encoding="utf-8")

    monkeypatch.setattr(runtime_mode, "UNIFIED_PID_FILE", unified_pid)
    monkeypatch.setattr(runtime_mode, "SHARD_HUB_PID_FILE", hub_pid)
    monkeypatch.setattr(runtime_mode, "SHARD_RUN_DIR", shard_run)
    monkeypatch.setattr(runtime_mode, "pid_alive", lambda pid: pid in {201, 202})

    summary = runtime_mode.runtime_instance_summary("shard")

    assert summary["mode"] == "shard"
    assert summary["label"] == "统一运行时（多实例）"
    assert summary["running_instances"] == 2
    assert [item["kind"] for item in summary["instances"]] == ["control", "message", "message"]
    assert all("worker" not in item["name"] and "hub" not in item["name"] for item in summary["instances"])
