"""Focused CLI tests: managed MaiBot start ordering, shared lock and sync gating."""

from __future__ import annotations

import hashlib
import socket
import sys
from typing import TYPE_CHECKING

from pallas.console.cli import maibot_aux
from pallas.product.agent_bridge.config import MaiBotBridgeConfig

if TYPE_CHECKING:
    from pathlib import Path


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _instance(root: Path, *, port: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(exist_ok=True)
    (root / "EULA.md").write_text("eula text", encoding="utf-8")
    (root / "PRIVACY.md").write_text("privacy text", encoding="utf-8")
    (root / "eula.confirmed").write_text(_md5("eula text"), encoding="utf-8")
    (root / "privacy.confirmed").write_text(_md5("privacy text"), encoding="utf-8")
    (root / "config" / "bot_config.toml").write_text(
        f'[maim_message]\nws_server_host = "127.0.0.1"\nws_server_port = {port}\n',
        encoding="utf-8",
    )
    (root / "config" / "model_config.toml").write_text("[models]\n", encoding="utf-8")
    (root / "bot.py").write_text("import time\nwhile True:\n    time.sleep(0.5)\n", encoding="utf-8")
    return root


def _bridge(url: str) -> MaiBotBridgeConfig:
    return MaiBotBridgeConfig(enabled=True, url=url, bot_id=10001, group_ids=frozenset({700001}), platform="pallas-qq")


def _patch_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(maibot_aux, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(maibot_aux, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(maibot_aux, "PID_FILE", tmp_path / "run" / "maibot.pid")
    monkeypatch.setattr(maibot_aux, "OWNER_FILE", tmp_path / "run" / "maibot.owner.json")
    monkeypatch.setattr(maibot_aux, "LOG_FILE", tmp_path / "logs" / "maibot.log")


def _lock_file(tmp_path: Path) -> Path:
    return tmp_path / "run" / "maibot.lock"


def _prepare(monkeypatch, tmp_path: Path, *, port: int, enabled="true", sync_enabled: bool = True):
    instance = _instance(tmp_path / "inst", port=port)
    values = {
        "MAIBOT_MANAGED_ENABLED": enabled,
        "MAIBOT_MANAGED_DIR": str(instance),
        "MAIBOT_MANAGED_PYTHON": sys.executable,
    }
    monkeypatch.setattr(maibot_aux, "repo_env_raw_value", lambda key: values.get(key))
    monkeypatch.setattr(
        "pallas.product.agent_bridge.config.load_bridge_config",
        lambda: _bridge(f"ws://127.0.0.1:{port}/ws"),
    )
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(maibot_aux, "_config_sync_enabled", lambda: sync_enabled)
    monkeypatch.setattr(maibot_aux, "linux_managed_supported", lambda: True)
    monkeypatch.setattr(maibot_aux, "maibot_aux_running", lambda: False)
    monkeypatch.setattr(maibot_aux, "_has_unresolved_orphan_group", lambda: False)
    monkeypatch.setattr(maibot_aux, "_port_connectable", lambda *a, **k: False)
    monkeypatch.setattr(maibot_aux, "_wait_transport_ready", lambda *a, **k: 0)
    return instance


def _patch_process(monkeypatch, *, owned: int | None):
    state = {"pid": owned}

    def current():
        return state["pid"]

    def spawn(cmd, *, cwd, env=None, log_path=None, inherit_env=True):
        state["pid"] = 909090
        return 909090

    monkeypatch.setattr(maibot_aux, "current_managed_process", current)
    monkeypatch.setattr(maibot_aux, "spawn_detached", spawn)
    return state


def test_default_off_creates_no_lock_or_process(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), enabled="false")
    _patch_process(monkeypatch, owned=None)
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    assert maibot_aux.start_maibot_aux().rc == 0
    assert spawned == []
    assert not _lock_file(tmp_path).exists()
    assert not (tmp_path / "run").exists()


def test_sync_runs_before_spawn(monkeypatch, tmp_path: Path):
    port = _free_port()
    _prepare(monkeypatch, tmp_path, port=port, sync_enabled=True)
    _patch_process(monkeypatch, owned=None)
    order: list[str] = []
    monkeypatch.setattr(
        maibot_aux, "_sync_instance", lambda config, *, dry_run: order.append(f"sync:{dry_run}") or True
    )
    real_spawn = maibot_aux.spawn_detached
    monkeypatch.setattr(
        maibot_aux,
        "spawn_detached",
        lambda *a, **k: order.append("spawn") or real_spawn(*a, **k),
    )
    result = maibot_aux.start_maibot_aux()
    assert result.rc == 0
    assert order == ["sync:False", "spawn"]
    assert _lock_file(tmp_path).exists()


def test_dry_run_writes_nothing(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)
    _patch_process(monkeypatch, owned=None)
    recorded: list[bool] = []
    monkeypatch.setattr(maibot_aux, "_sync_instance", lambda config, *, dry_run: recorded.append(dry_run) or True)
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    assert maibot_aux.start_maibot_aux(dry_run=True).rc == 0
    assert recorded == [True]
    assert spawned == []
    assert not _lock_file(tmp_path).exists()
    assert not (tmp_path / "run").exists()


def test_unknown_live_pid_rejected_before_sync(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)
    _patch_process(monkeypatch, owned=None)
    monkeypatch.setattr(maibot_aux, "maibot_aux_running", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(maibot_aux, "_sync_instance", lambda config, *, dry_run: calls.append("sync") or True)
    assert maibot_aux.start_maibot_aux().rc == 1
    assert calls == []


def test_orphan_group_rejected_before_sync(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)
    _patch_process(monkeypatch, owned=None)
    monkeypatch.setattr(maibot_aux, "_has_unresolved_orphan_group", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(maibot_aux, "_sync_instance", lambda config, *, dry_run: calls.append("sync") or True)
    assert maibot_aux.start_maibot_aux().rc == 1
    assert calls == []


def test_occupied_port_rejected_before_sync(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)
    _patch_process(monkeypatch, owned=None)
    monkeypatch.setattr(maibot_aux, "_port_connectable", lambda *a, **k: True)
    calls: list[str] = []
    monkeypatch.setattr(maibot_aux, "_sync_instance", lambda config, *, dry_run: calls.append("sync") or True)
    assert maibot_aux.start_maibot_aux().rc == 1
    assert calls == []


def test_running_owned_with_sync_requires_restart(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)
    _patch_process(monkeypatch, owned=4321)
    calls: list[str] = []
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "_sync_instance", lambda config, *, dry_run: calls.append("sync") or True)
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    assert maibot_aux.start_maibot_aux().rc == 1
    assert calls == []  # never rewrites files while running
    assert spawned == []


def test_running_owned_without_sync_keeps_old_wait(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=False)
    _patch_process(monkeypatch, owned=4321)
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    result = maibot_aux.start_maibot_aux()
    assert result.rc == 0
    assert spawned == []


def test_sync_failure_does_not_spawn(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)
    _patch_process(monkeypatch, owned=None)
    monkeypatch.setattr(maibot_aux, "_sync_instance", lambda config, *, dry_run: False)
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    assert maibot_aux.start_maibot_aux().rc == 1
    assert spawned == []


def test_invalid_sync_switch_rejected(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)

    def boom():
        raise maibot_aux.ManagedConfigError("bad switch")

    monkeypatch.setattr(maibot_aux, "_config_sync_enabled", boom)
    _patch_process(monkeypatch, owned=None)
    assert maibot_aux.start_maibot_aux().rc == 1


def test_start_and_stop_share_instance_lock(monkeypatch, tmp_path: Path):
    from contextlib import contextmanager

    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=False)
    _patch_process(monkeypatch, owned=None)
    acquired: list[Path] = []

    @contextmanager
    def fake_lock(path):
        acquired.append(path)
        yield

    monkeypatch.setattr(maibot_aux, "interprocess_file_lock", fake_lock)
    monkeypatch.setattr(maibot_aux, "_stop_owned_pid", lambda *a, **k: True)
    monkeypatch.setattr(maibot_aux, "report_process_stop", lambda *a, **k: None)

    assert maibot_aux.start_maibot_aux().rc == 0
    assert maibot_aux.stop_maibot_aux() is True
    assert acquired == [_lock_file(tmp_path), _lock_file(tmp_path)]  # start and stop share the lock


def test_unsupported_platform_rejected_before_sync_and_files(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)
    _patch_process(monkeypatch, owned=None)
    monkeypatch.setattr(maibot_aux, "linux_managed_supported", lambda: False)
    calls: list[str] = []
    monkeypatch.setattr(maibot_aux, "_sync_instance", lambda config, *, dry_run: calls.append("sync") or True)
    assert maibot_aux.start_maibot_aux().rc == 1
    assert calls == []
    assert not (tmp_path / "run").exists()


def test_dry_run_rejects_occupied_port(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)
    _patch_process(monkeypatch, owned=None)
    monkeypatch.setattr(maibot_aux, "_sync_instance", lambda config, *, dry_run: True)
    monkeypatch.setattr(maibot_aux, "_port_connectable", lambda *a, **k: True)
    assert maibot_aux.start_maibot_aux(dry_run=True).rc == 1
    assert not (tmp_path / "run").exists()


def test_off_stop_creates_no_runtime_dir(monkeypatch, tmp_path: Path):
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(maibot_aux, "repo_env_raw_value", lambda _key: None)
    assert maibot_aux.stop_maibot_aux() is True
    assert not (tmp_path / "run").exists()


def test_live_off_existing_instance_still_stops(monkeypatch, tmp_path: Path):
    import json

    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(maibot_aux, "repo_env_raw_value", lambda _key: None)  # managed turned off
    maibot_aux.write_pid_file(maibot_aux.PID_FILE, 555)
    maibot_aux.OWNER_FILE.write_text(
        json.dumps({"pid": 555, "instance_dir": str(tmp_path), "starttime": "x", "boot_id": "b"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(maibot_aux, "current_managed_process", lambda: 555)
    monkeypatch.setattr(maibot_aux, "_stop_owned_pid", lambda *a, **k: True)
    monkeypatch.setattr(maibot_aux, "report_process_stop", lambda *a, **k: None)
    assert maibot_aux.stop_maibot_aux() is True
    assert maibot_aux.read_pid_file(maibot_aux.PID_FILE) is None


def test_stop_spawned_pid_holds_instance_lock(monkeypatch, tmp_path: Path):
    from contextlib import contextmanager

    _patch_paths(monkeypatch, tmp_path)
    maibot_aux.write_pid_file(maibot_aux.PID_FILE, 321)
    order: list[str] = []

    @contextmanager
    def fake_lock(_path):
        order.append("lock")
        yield
        order.append("unlock")

    monkeypatch.setattr(maibot_aux, "interprocess_file_lock", fake_lock)
    monkeypatch.setattr(maibot_aux, "_stop_owned_pid", lambda pid, force=False: order.append("stop") or True)
    monkeypatch.setattr(maibot_aux, "read_pid_file", lambda _p: order.append("read") or 321)
    monkeypatch.setattr(maibot_aux, "clear_pid_file", lambda _p: order.append("clear"))
    monkeypatch.setattr(maibot_aux, "_clear_owner", lambda: order.append("owner"))

    assert maibot_aux.stop_spawned_pid(321) is True
    assert order == ["lock", "stop", "read", "clear", "owner", "unlock"]


def test_config_sync_requested_tracks_managed_and_switch(monkeypatch, tmp_path: Path):
    _prepare(monkeypatch, tmp_path, port=_free_port(), sync_enabled=True)
    assert maibot_aux.config_sync_requested() is True
    monkeypatch.setattr(maibot_aux, "_config_sync_enabled", lambda: False)
    assert maibot_aux.config_sync_requested() is False

    def boom():
        raise maibot_aux.ManagedConfigError("bad")

    monkeypatch.setattr(maibot_aux, "load_managed_config", boom)
    assert maibot_aux.config_sync_requested() is False
