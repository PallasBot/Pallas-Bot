from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pallas.console.cli import bot_process, process_util, unified_lifecycle

if TYPE_CHECKING:
    from pathlib import Path


def test_pid_alive_zero():
    assert process_util.pid_alive(0) is False


def test_pid_alive_current_process():
    assert process_util.pid_alive(os.getpid()) is True


def test_read_write_pid_file(tmp_path: Path):
    path = tmp_path / "bot.pid"
    assert process_util.read_pid_file(path) is None
    process_util.write_pid_file(path, 12345)
    assert process_util.read_pid_file(path) == 12345
    process_util.clear_pid_file(path)
    assert process_util.read_pid_file(path) is None


def test_bash_missing_message_mentions_uv_run_pallas():
    msg = process_util.bash_missing_message(purpose="测试")
    assert "测试" in msg
    assert "bash" in msg.lower()


def test_run_bot_lifecycle_unified_delegates(monkeypatch):
    called: dict[str, object] = {}

    def fake_run(action: str, *, skip_port_sync: bool = False) -> int:
        called["action"] = action
        called["skip"] = skip_port_sync
        return 0

    monkeypatch.setattr(bot_process, "run_unified_action", fake_run)
    monkeypatch.setattr(bot_process, "resolve_bot_mode", lambda mode: "unified")
    assert bot_process.run_bot_lifecycle("start", mode="unified", extra_args=["--skip-port-sync"]) == 0
    assert called == {"action": "start", "skip": True}


def test_run_bot_lifecycle_shard_without_bash(monkeypatch, tmp_path: Path, capsys):
    script = tmp_path / "run_sharded_bot.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr(bot_process, "SHARD_SCRIPT", script)
    monkeypatch.setattr(bot_process, "resolve_bot_mode", lambda mode: "shard")
    monkeypatch.setattr(bot_process, "resolve_bash", lambda: None)
    monkeypatch.setattr(bot_process, "is_windows", lambda: True)
    assert bot_process.run_bot_lifecycle("start", mode="shard") == 1
    err = capsys.readouterr().err
    assert "bash" in err.lower()
    assert "unified" in err.lower()


def test_run_bot_lifecycle_shard_with_bash(monkeypatch, tmp_path: Path):
    script = tmp_path / "run_sharded_bot.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    bash = tmp_path / "bash"
    bash.write_text("", encoding="utf-8")
    monkeypatch.setattr(bot_process, "SHARD_SCRIPT", script)
    monkeypatch.setattr(bot_process, "resolve_bot_mode", lambda mode: "shard")
    monkeypatch.setattr(bot_process, "resolve_bash", lambda: bash)

    def fake_run(script_path, args=(), *, cwd=None, env=None, purpose=""):
        assert script_path == script
        assert args[0] == "status"
        return 0

    monkeypatch.setattr(bot_process, "run_bash_script", fake_run)
    assert bot_process.run_bot_lifecycle("status", mode="shard") == 0


def test_schedule_bot_restart_uses_python_not_bash(monkeypatch):
    monkeypatch.setattr(bot_process, "resolve_bot_mode", lambda mode: "unified")
    spawned: list[list[str]] = []

    def fake_spawn(cmd, *, cwd, env=None, log_path=None):
        spawned.append(list(cmd))
        return 1

    monkeypatch.setattr(bot_process, "spawn_detached", fake_spawn)
    assert bot_process.schedule_bot_restart(mode="unified", delay_s=0.1) is True
    assert len(spawned) == 1
    assert "-c" in spawned[0]
    assert "restart_after_delay" in spawned[0][-1]


def test_unified_status_prints(monkeypatch, capsys):
    monkeypatch.setattr(unified_lifecycle, "read_listen_port", lambda: 8088)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: False)
    assert unified_lifecycle.status_bot() == 0
    out = capsys.readouterr().out
    assert "未运行" in out
    assert "8088" in out


def test_unified_start_when_already_running(monkeypatch, capsys):
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: True)
    monkeypatch.setattr(unified_lifecycle, "read_pid_file", lambda _p: 42)
    assert unified_lifecycle.start_bot() == 0
    assert "已在运行" in capsys.readouterr().out


def test_unified_start_spawns(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(unified_lifecycle, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(unified_lifecycle, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(unified_lifecycle, "PID_FILE", tmp_path / "run" / "bot.pid")
    monkeypatch.setattr(unified_lifecycle, "LOG_FILE", tmp_path / "logs" / "bot.log")
    monkeypatch.setattr(unified_lifecycle, "ACCOUNTS_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(unified_lifecycle, "read_listen_port", lambda: 9090)
    monkeypatch.setattr(unified_lifecycle, "prepare_unified_ports", lambda port, *, skip_port_sync: 0)
    monkeypatch.setattr(unified_lifecycle.time, "sleep", lambda _s: None)

    states = {"started": False}

    def is_running() -> bool:
        return states["started"]

    def fake_spawn(cmd, *, cwd, env=None, log_path=None):
        states["cmd"] = list(cmd)
        states["env"] = dict(env or {})
        states["started"] = True
        return 4242

    monkeypatch.setattr(unified_lifecycle, "is_bot_running", is_running)
    monkeypatch.setattr(unified_lifecycle, "spawn_detached", fake_spawn)
    assert unified_lifecycle.start_bot() == 0
    assert states["env"]["PALLAS_BOT_ROLE"] == "unified"
    assert states["env"]["PORT"] == "9090"
    assert "bot.py" in states["cmd"]
    assert unified_lifecycle.read_pid_file(unified_lifecycle.PID_FILE) == 4242
    assert "已启动" in capsys.readouterr().out
