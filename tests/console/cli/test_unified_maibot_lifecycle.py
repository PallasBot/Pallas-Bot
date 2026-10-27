"""Unified lifecycle ordering/rollback for the managed MaiBot pre-step."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pallas.console.cli import unified_lifecycle

if TYPE_CHECKING:
    from pathlib import Path


def _arm_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(unified_lifecycle, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(unified_lifecycle, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(unified_lifecycle, "PID_FILE", tmp_path / "run" / "bot.pid")
    monkeypatch.setattr(unified_lifecycle, "ACCOUNTS_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(unified_lifecycle, "read_listen_port", lambda: 9090)
    monkeypatch.setattr(unified_lifecycle, "prepare_unified_ports", lambda port, *, skip_port_sync: 0)
    monkeypatch.setattr(unified_lifecycle.time, "sleep", lambda _s: None)
    # safety: never signal a real pid from tests
    monkeypatch.setattr(unified_lifecycle, "pid_alive", lambda _pid: False)
    monkeypatch.setattr(unified_lifecycle, "stop_pid", lambda *a, **k: True)


def test_default_off_does_not_touch_maibot(monkeypatch):
    from pallas.console.cli import maibot_aux

    monkeypatch.setattr(maibot_aux, "repo_env_raw_value", lambda _key: None)
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn")))
    rc, pid = unified_lifecycle.start_managed_maibot()
    assert (rc, pid) == (0, None)


def test_managed_started_before_detached_spawn(monkeypatch, tmp_path: Path):
    order: list[str] = []
    state = {"running": False}
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: state["running"])
    monkeypatch.setattr(unified_lifecycle, "cleanup_launcher_logs", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "launcher_log_path", lambda: tmp_path / "logs" / "bot.log")
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: order.append("managed") or (0, True))
    monkeypatch.setattr(unified_lifecycle, "wait_for_bot_startup", lambda _p: True)

    def spawn(cmd, *, cwd, env=None, log_path=None):
        order.append("spawn")
        state["running"] = True
        return 4242

    monkeypatch.setattr(unified_lifecycle, "spawn_detached", spawn)
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: 0)

    assert unified_lifecycle.start_bot(detach=True) == 0
    assert order == ["managed", "spawn"]


def test_managed_started_before_foreground_runpy(monkeypatch, tmp_path: Path):
    order: list[str] = []
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: False)
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: order.append("managed") or (0, 4242))
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: 0)
    monkeypatch.setattr(unified_lifecycle, "stop_aux_services", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "stop_spawned_maibot", lambda pid: order.append(("stop", pid)))
    monkeypatch.setattr(unified_lifecycle.runpy, "run_path", lambda path, run_name: order.append("runpy"))
    monkeypatch.setattr(unified_lifecycle, "write_pid_file", lambda _p, _pid: None)
    monkeypatch.setattr(unified_lifecycle, "clear_pid_file", lambda _p: None)

    assert unified_lifecycle.start_bot(detach=False) == 0
    assert order == ["managed", "runpy", ("stop", 4242)]


def test_rollback_stops_managed_only_when_spawned(monkeypatch, tmp_path: Path):
    state = {"running": False}
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "cleanup_launcher_logs", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "launcher_log_path", lambda: tmp_path / "logs" / "bot.log")
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: state["running"])
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: 1)  # aux fails
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: (0, 4242))
    stopped: list = []
    monkeypatch.setattr(unified_lifecycle, "stop_spawned_maibot", lambda pid: stopped.append(pid))
    monkeypatch.setattr(unified_lifecycle, "stop_bot", lambda *, stop_managed=True: 1)

    def spawn(*_a, **_k):
        state["running"] = True
        return 4242

    monkeypatch.setattr(unified_lifecycle, "spawn_detached", spawn)

    assert unified_lifecycle.start_bot(detach=True) == 1
    assert stopped == [4242]


def test_rollback_keeps_preexisting_managed_on_spawn_failure(monkeypatch, tmp_path: Path):
    from pallas.console.cli import maibot_aux

    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: False)
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: (0, None))  # already running
    stopped: list = []
    monkeypatch.setattr(maibot_aux, "stop_spawned_pid", lambda pid: stopped.append(pid))

    def spawn(*_a, **_k):
        raise OSError("boom")

    monkeypatch.setattr(unified_lifecycle, "spawn_detached", spawn)

    assert unified_lifecycle.start_bot(detach=True) == 1
    # not spawned this call -> must not stop the pre-existing managed instance
    assert stopped == []


def test_stop_bot_stops_managed_after_pallas(monkeypatch, tmp_path: Path):
    order: list[str] = []
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "stop_aux_services", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "read_pid_file", lambda _p: 555)
    monkeypatch.setattr(unified_lifecycle, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(unified_lifecycle, "clear_pid_file", lambda _p: None)
    monkeypatch.setattr(unified_lifecycle, "stop_pid", lambda pid, timeout_s: order.append("pallas") or True)
    monkeypatch.setattr(unified_lifecycle, "stop_managed_maibot", lambda: order.append("maibot") or True)

    assert unified_lifecycle.stop_bot() == 0
    assert order == ["pallas", "maibot"]


def test_stop_bot_can_skip_managed(monkeypatch, tmp_path: Path):
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "stop_aux_services", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "read_pid_file", lambda _p: None)
    monkeypatch.setattr(unified_lifecycle, "clear_pid_file", lambda _p: None)
    called: list = []
    monkeypatch.setattr(unified_lifecycle, "stop_managed_maibot", lambda **k: called.append(1))

    assert unified_lifecycle.stop_bot(stop_managed=False) == 0
    assert called == []


def test_invalid_managed_config_fails_unified_without_spawn_or_runpy(monkeypatch, tmp_path: Path, capsys):
    from pallas.console.cli import maibot_aux

    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: False)
    monkeypatch.setattr(unified_lifecycle, "cleanup_launcher_logs", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: 0)
    monkeypatch.setattr(
        maibot_aux, "repo_env_raw_value", lambda key: "maybe" if key == "MAIBOT_MANAGED_ENABLED" else None
    )
    spawned: list = []
    executed: list = []
    monkeypatch.setattr(unified_lifecycle, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    monkeypatch.setattr(unified_lifecycle.runpy, "run_path", lambda *a, **k: executed.append(1))

    assert unified_lifecycle.start_bot(detach=True) == 1
    assert spawned == []
    assert executed == []

    assert unified_lifecycle.start_bot(detach=False) == 1
    assert spawned == []
    assert executed == []
    capsys.readouterr()


def test_existing_pallas_managed_missing_requires_restart(monkeypatch, tmp_path: Path, capsys):
    from pallas.console.cli import maibot_aux

    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: True)
    monkeypatch.setattr(unified_lifecycle, "read_pid_file", lambda _p: 42)
    monkeypatch.setattr(maibot_aux, "load_managed_config", lambda: maibot_aux.ManagedMaiBotConfig(enabled=True))
    monkeypatch.setattr(maibot_aux, "current_managed_process", lambda: None)
    aux_called: list = []
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: aux_called.append(1) or 0)

    assert unified_lifecycle.start_bot(detach=True) == 1
    out = capsys.readouterr().err
    assert "restart" in out


def test_existing_pallas_managed_running_is_idempotent(monkeypatch, tmp_path: Path):
    from pallas.console.cli import maibot_aux

    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: True)
    monkeypatch.setattr(unified_lifecycle, "read_pid_file", lambda _p: 42)
    monkeypatch.setattr(maibot_aux, "load_managed_config", lambda: maibot_aux.ManagedMaiBotConfig(enabled=True))
    monkeypatch.setattr(maibot_aux, "current_managed_process", lambda: 999)
    aux_called: list = []
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: aux_called.append(1) or 0)

    assert unified_lifecycle.start_bot(detach=True) == 0
    assert aux_called == [1]


def test_existing_pallas_managed_off_keeps_old_behavior(monkeypatch, tmp_path: Path):
    from pallas.console.cli import maibot_aux

    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: True)
    monkeypatch.setattr(unified_lifecycle, "read_pid_file", lambda _p: 42)
    monkeypatch.setattr(maibot_aux, "load_managed_config", lambda: maibot_aux.ManagedMaiBotConfig(enabled=False))
    aux_called: list = []
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: aux_called.append(1) or 0)

    assert unified_lifecycle.start_bot(detach=True) == 0
    assert aux_called == [1]


def test_existing_pallas_invalid_managed_returns_nonzero(monkeypatch, tmp_path: Path, capsys):
    from pallas.console.cli import maibot_aux

    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: True)
    monkeypatch.setattr(unified_lifecycle, "read_pid_file", lambda _p: 42)

    def boom():
        raise maibot_aux.ManagedConfigError("bad")

    monkeypatch.setattr(maibot_aux, "load_managed_config", boom)
    assert unified_lifecycle.start_bot(detach=True) == 1
    capsys.readouterr()


def test_detached_bot_failure_rolls_back_spawned_managed(monkeypatch, tmp_path: Path):
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "cleanup_launcher_logs", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "launcher_log_path", lambda: tmp_path / "logs" / "bot.log")
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: False)
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: (0, 777))
    monkeypatch.setattr(unified_lifecycle, "spawn_detached", lambda *a, **k: 1)
    monkeypatch.setattr(unified_lifecycle, "write_pid_file", lambda *a: None)
    monkeypatch.setattr(unified_lifecycle, "clear_pid_file", lambda *a: None)
    monkeypatch.setattr(unified_lifecycle, "print_startup_failure", lambda *a: None)
    stopped: list = []
    monkeypatch.setattr(unified_lifecycle, "stop_spawned_maibot", lambda pid: stopped.append(pid))

    assert unified_lifecycle.start_bot(detach=True) == 1
    assert stopped == [777]


def test_stop_bot_propagates_managed_failure(monkeypatch, tmp_path: Path):
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "stop_aux_services", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "read_pid_file", lambda _p: None)
    monkeypatch.setattr(unified_lifecycle, "stop_managed_maibot", lambda: False)

    assert unified_lifecycle.stop_bot() == 1


def test_restart_cancels_when_stop_fails(monkeypatch):
    calls: list = []
    monkeypatch.setattr(unified_lifecycle, "stop_bot", lambda: 1)
    monkeypatch.setattr(unified_lifecycle, "start_bot", lambda **k: calls.append("start") or 0)

    assert unified_lifecycle.run_unified_action("restart") == 1
    assert calls == []


def test_foreground_shutdown_callback_cleanup_is_idempotent(monkeypatch, tmp_path: Path):
    from pallas.core.foundation import asgi_runner

    order: list = []
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: False)
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: (0, 4242))
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: 0)
    monkeypatch.setattr(unified_lifecycle, "write_pid_file", lambda *a: None)
    monkeypatch.setattr(unified_lifecycle, "clear_pid_file", lambda *a: order.append("clear"))
    monkeypatch.setattr(unified_lifecycle, "stop_aux_services", lambda: order.append("aux"))
    monkeypatch.setattr(unified_lifecycle, "stop_spawned_maibot", lambda pid: order.append(("maibot", pid)))

    def fake_runpy(path, run_name):
        asgi_runner.run_process_shutdown_callback()  # simulates os._exit path
        raise SystemExit(0)

    monkeypatch.setattr(unified_lifecycle.runpy, "run_path", fake_runpy)

    with pytest.raises(SystemExit):
        unified_lifecycle.start_bot(detach=False)
    # callback does the full cleanup once; the finally must not repeat it
    assert order == ["clear", "aux", ("maibot", 4242)]


def test_detached_failure_stops_specific_bot_pid_then_managed(monkeypatch, tmp_path: Path):
    order: list = []
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "cleanup_launcher_logs", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "launcher_log_path", lambda: tmp_path / "logs" / "bot.log")
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: False)
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: (0, 777))
    monkeypatch.setattr(unified_lifecycle, "spawn_detached", lambda *a, **k: 321)
    monkeypatch.setattr(unified_lifecycle, "write_pid_file", lambda *a: None)
    monkeypatch.setattr(unified_lifecycle, "print_startup_failure", lambda *a: None)
    monkeypatch.setattr(unified_lifecycle, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(unified_lifecycle, "stop_pid", lambda pid, timeout_s: order.append(("bot", pid)) or True)
    monkeypatch.setattr(unified_lifecycle, "stop_spawned_maibot", lambda pid: order.append(("maibot", pid)))

    assert unified_lifecycle.start_bot(detach=True) == 1
    assert order == [("bot", 321), ("maibot", 777)]


def test_detached_rollback_stops_aux_bot_then_managed(monkeypatch, tmp_path: Path):
    order: list = []
    state = {"running": False}
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "cleanup_launcher_logs", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "launcher_log_path", lambda: tmp_path / "logs" / "bot.log")
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: state["running"])
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: (0, 777))

    def spawn(*_a, **_k):
        state["running"] = True
        return 321

    monkeypatch.setattr(unified_lifecycle, "spawn_detached", spawn)
    monkeypatch.setattr(unified_lifecycle, "write_pid_file", lambda *a: None)
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: 0)  # aux succeeds
    monkeypatch.setattr(unified_lifecycle, "stop_aux_services", lambda: order.append("aux"))
    monkeypatch.setattr(unified_lifecycle, "wait_for_bot_startup", lambda _p: False)  # bot startup fails
    monkeypatch.setattr(unified_lifecycle, "print_startup_failure", lambda *a: None)
    monkeypatch.setattr(unified_lifecycle, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(unified_lifecycle, "stop_pid", lambda pid, timeout_s: order.append(("bot", pid)) or True)
    monkeypatch.setattr(unified_lifecycle, "stop_spawned_maibot", lambda pid: order.append(("maibot", pid)))

    assert unified_lifecycle.start_bot(detach=True) == 1
    assert order == ["aux", ("bot", 321), ("maibot", 777)]


def test_rollback_without_spawn_does_not_stop_aux(monkeypatch, tmp_path: Path):
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: False)
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: (0, None))
    aux_stopped: list = []
    monkeypatch.setattr(unified_lifecycle, "stop_aux_services", lambda: aux_stopped.append(1))

    def spawn(*_a, **_k):
        raise OSError("boom")

    monkeypatch.setattr(unified_lifecycle, "spawn_detached", spawn)

    assert unified_lifecycle.start_bot(detach=True) == 1
    assert aux_stopped == []


def test_rollback_continues_when_aux_stop_raises(monkeypatch, tmp_path: Path):
    order: list = []
    state = {"running": False}
    _arm_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(unified_lifecycle, "cleanup_launcher_logs", lambda: None)
    monkeypatch.setattr(unified_lifecycle, "launcher_log_path", lambda: tmp_path / "logs" / "bot.log")
    monkeypatch.setattr(unified_lifecycle, "is_bot_running", lambda: state["running"])
    monkeypatch.setattr(unified_lifecycle, "start_managed_maibot", lambda: (0, 777))

    def spawn(*_a, **_k):
        state["running"] = True
        return 321

    monkeypatch.setattr(unified_lifecycle, "spawn_detached", spawn)
    monkeypatch.setattr(unified_lifecycle, "write_pid_file", lambda *a: None)
    monkeypatch.setattr(unified_lifecycle, "start_aux_services", lambda: 0)
    monkeypatch.setattr(unified_lifecycle, "wait_for_bot_startup", lambda _p: False)
    monkeypatch.setattr(unified_lifecycle, "print_startup_failure", lambda *a: None)
    monkeypatch.setattr(unified_lifecycle, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(unified_lifecycle, "stop_pid", lambda pid, timeout_s: order.append(("bot", pid)) or True)
    monkeypatch.setattr(unified_lifecycle, "stop_spawned_maibot", lambda pid: order.append(("maibot", pid)))

    def boom():
        raise RuntimeError("aux stop failed")

    monkeypatch.setattr(unified_lifecycle, "stop_aux_services", boom)

    with pytest.raises(RuntimeError):
        unified_lifecycle.start_bot(detach=True)
    # even when aux stop raises, the specific bot pid and this call's managed pid are rolled back
    assert order == [("bot", 321), ("maibot", 777)]
