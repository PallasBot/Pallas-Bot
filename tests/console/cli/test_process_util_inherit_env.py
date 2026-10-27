"""spawn_detached env handling: inherit_env=False must not resurrect parent keys."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from pallas.console.cli import process_util

if TYPE_CHECKING:
    from pathlib import Path


def test_spawn_detached_default_merges_parent_env(monkeypatch, tmp_path: Path):
    captured: dict = {}

    class _Proc:
        pid = 111

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setenv("VIRTUAL_ENV", "/parent/venv")
    monkeypatch.setattr(process_util.subprocess, "Popen", fake_popen)

    process_util.spawn_detached(["x"], cwd=tmp_path, env={"KEEP": "1"})

    assert captured["env"]["VIRTUAL_ENV"] == "/parent/venv"
    assert captured["env"]["KEEP"] == "1"


def test_spawn_detached_inherit_env_false_keeps_only_provided(monkeypatch, tmp_path: Path):
    captured: dict = {}

    class _Proc:
        pid = 222

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setenv("VIRTUAL_ENV", "/parent/venv")
    monkeypatch.setenv("UV_PROJECT", "/parent/project")
    monkeypatch.setenv("SOME_PARENT_KEY", "should-not-leak")
    monkeypatch.setattr(process_util.subprocess, "Popen", fake_popen)

    process_util.spawn_detached(
        ["x"],
        cwd=tmp_path,
        env={"MAIBOT_INSTANCE_DIR": "/inst", "PYTHONUNBUFFERED": "1"},
        inherit_env=False,
    )

    env = captured["env"]
    assert env["MAIBOT_INSTANCE_DIR"] == "/inst"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert "VIRTUAL_ENV" not in env
    assert "UV_PROJECT" not in env
    assert "SOME_PARENT_KEY" not in env
    assert os.environ.get("VIRTUAL_ENV") == "/parent/venv"  # parent untouched


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )


def test_group_has_live_member_detects_spawned_child():
    proc = _spawn_sleeper()
    try:
        assert process_util.group_has_live_member(proc.pid) is True
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_stop_pid_wait_for_group_stops_child():
    proc = _spawn_sleeper()
    assert process_util.stop_pid(proc.pid, timeout_s=5.0, wait_for_group=True) is True
    proc.wait(timeout=5)
    assert process_util.pid_alive(proc.pid) is False


def test_stop_pid_default_still_returns_true_for_dead_pid():
    proc = _spawn_sleeper()
    proc.kill()
    proc.wait(timeout=5)
    assert process_util.stop_pid(proc.pid, timeout_s=1.0) is True
    assert process_util.stop_pid(0) is True
