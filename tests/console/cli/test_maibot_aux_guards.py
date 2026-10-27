"""Guard tests for managed MaiBot: URL/port/family, ownership, env, cleanup."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from pallas.console.cli import maibot_aux, process_util
from pallas.product.agent_bridge.config import MaiBotBridgeConfig

if TYPE_CHECKING:
    from pathlib import Path


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _bridge(url: str, *, enabled: bool = True) -> MaiBotBridgeConfig:
    return MaiBotBridgeConfig(
        enabled=enabled, url=url, bot_id=10001, group_ids=frozenset({700001}), platform="pallas-qq"
    )


def _make_instance(
    root: Path,
    *,
    port: int,
    host: str = "127.0.0.1",
    eula: str = "eula text",
    bot_py: str | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(exist_ok=True)
    (root / "EULA.md").write_text(eula, encoding="utf-8")
    (root / "PRIVACY.md").write_text("privacy text", encoding="utf-8")
    (root / "eula.confirmed").write_text(_md5(eula), encoding="utf-8")
    (root / "privacy.confirmed").write_text(_md5("privacy text"), encoding="utf-8")
    (root / "config" / "bot_config.toml").write_text(
        f'[maim_message]\nws_server_host = "{host}"\nws_server_port = {port}\n',
        encoding="utf-8",
    )
    (root / "config" / "model_config.toml").write_text("[models]\n", encoding="utf-8")
    if bot_py is None:
        keys = [
            "VIRTUAL_ENV",
            "UV_PROJECT",
            "PYTHONPATH",
            "MAIBOT_WORKER_PROCESS",
            "EULA_AGREE",
            "MAIBOT_INSTANCE_DIR",
            "PYTHONUNBUFFERED",
        ]
        bot_py = (
            "import json, os, socket, time\n"
            f"keys = {keys!r}\n"
            "json.dump({k: os.environ.get(k) for k in keys}, open('env_dump.json', 'w'))\n"
            "s = socket.socket()\n"
            "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            f"s.bind(('{host}', {port}))\n"
            "s.listen()\n"
            "while True:\n"
            "    time.sleep(0.5)\n"
        )
    (root / "bot.py").write_text(bot_py, encoding="utf-8")
    return root


def _patch_env(monkeypatch, *, enabled="true", instance_dir=None, python=None, bridge_url=None, bridge_enabled=True):
    values = {"MAIBOT_MANAGED_ENABLED": enabled}
    if instance_dir is not None:
        values["MAIBOT_MANAGED_DIR"] = str(instance_dir)
    if python is not None:
        values["MAIBOT_MANAGED_PYTHON"] = str(python)
    monkeypatch.setattr(maibot_aux, "repo_env_raw_value", lambda key: values.get(key))
    url = bridge_url if bridge_url is not None else "ws://127.0.0.1:8000/ws"
    monkeypatch.setattr(
        "pallas.product.agent_bridge.config.load_bridge_config",
        lambda: _bridge(url, enabled=bridge_enabled),
    )


def _patch_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(maibot_aux, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(maibot_aux, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(maibot_aux, "PID_FILE", tmp_path / "run" / "maibot.pid")
    monkeypatch.setattr(maibot_aux, "OWNER_FILE", tmp_path / "run" / "maibot.owner.json")
    monkeypatch.setattr(maibot_aux, "LOG_FILE", tmp_path / "logs" / "maibot.log")


# ------------------------------------------------------------------ URL/port


@pytest.mark.parametrize(
    "url",
    [
        "ws://127.0.0.1:99999/ws",
        "ws://127.0.0.1:0/ws",
        "ws://127.0.0.1:8000/other",
        "ws://127.0.0.1:8000/ws?token=secret",
        "ws://user:pw@127.0.0.1:8000/ws",
        "ws://127.0.0.1:8000/ws#frag",
        "wss://127.0.0.1:8000/ws",
        "ws://10.0.0.5:8000/ws",
        "ws://[::1:8000/ws",
        "ws://127.0.0.1/ws",
        "garbage",
    ],
)
def test_bridge_host_port_rejects_bad_urls(url):
    assert maibot_aux.bridge_host_port(url) is None


def test_bridge_host_port_accepts_valid_loopback():
    assert maibot_aux.bridge_host_port("ws://127.0.0.1:8000/ws") == ("127.0.0.1", 8000)
    assert maibot_aux.bridge_host_port("ws://[::1]:8000/ws") == ("::1", 8000)


@pytest.mark.parametrize("url", ["ws://0.0.0.0:8000/ws", "ws://[::]:8000/ws"])
def test_bridge_host_port_rejects_wildcard_listen_addresses(url):
    assert maibot_aux.bridge_host_port(url) is None


def test_validate_does_not_echo_url_secrets(monkeypatch, tmp_path: Path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    _patch_env(
        monkeypatch,
        instance_dir=instance,
        python=sys.executable,
        bridge_url="wss://user:secret@10.0.0.5:8000/ws?token=abc",
    )
    config = maibot_aux.load_managed_config()
    problems = maibot_aux.validate_managed_instance(config, _bridge("wss://user:secret@10.0.0.5:8000/ws?token=abc"))
    assert problems
    joined = "\n".join(problems)
    assert "secret" not in joined
    assert "token=abc" not in joined
    assert "10.0.0.5" not in joined


@pytest.mark.parametrize(
    ("instance_host", "bridge_url", "ok"),
    [
        ("0.0.0.0", "ws://127.0.0.1:8000/ws", True),
        ("::", "ws://127.0.0.1:8000/ws", False),  # IPv6-only listen vs IPv4 bridge
        ("0.0.0.0", "ws://[::1]:8000/ws", False),
        ("::", "ws://[::1]:8000/ws", True),
        ("127.0.0.1", "ws://127.0.0.1:8000/ws", True),
    ],
)
def test_validate_host_family(monkeypatch, tmp_path: Path, instance_host, bridge_url, ok):
    port = 8000
    instance = _make_instance(tmp_path / "inst", port=port, host=instance_host)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=bridge_url)
    config = maibot_aux.load_managed_config()
    problems = maibot_aux.validate_managed_instance(config, _bridge(bridge_url))
    family_problems = [p for p in problems if "address family" in p or "family" in p or "监听" in p]
    assert bool(family_problems) is (not ok), problems


def test_validate_rejects_non_executable_interpreter(monkeypatch, tmp_path: Path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    fake_python = tmp_path / "python-notexec"
    fake_python.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_python.chmod(0o644)
    _patch_env(monkeypatch, instance_dir=instance, python=fake_python, bridge_url="ws://127.0.0.1:8000/ws")
    config = maibot_aux.load_managed_config()
    problems = maibot_aux.validate_managed_instance(config, _bridge("ws://127.0.0.1:8000/ws"))
    assert any("可执行" in p for p in problems), problems


def test_validate_bad_encoding_protocol_is_controlled(monkeypatch, tmp_path: Path):
    instance = _make_instance(tmp_path / "inst", port=8000)
    (instance / "EULA.md").write_bytes(b"\xff\xfe invalid utf8 \x80")
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url="ws://127.0.0.1:8000/ws")
    config = maibot_aux.load_managed_config()
    problems = maibot_aux.validate_managed_instance(config, _bridge("ws://127.0.0.1:8000/ws"))
    assert any("协议" in p for p in problems), problems


# ------------------------------------------------------------------ ownership


def test_current_managed_process_none_without_pid_file(monkeypatch, tmp_path: Path):
    _patch_paths(monkeypatch, tmp_path)
    assert maibot_aux.current_managed_process() is None


def test_current_managed_process_rejects_unrelated_live_pid(monkeypatch, tmp_path: Path):
    _patch_paths(monkeypatch, tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])  # noqa: S603
    try:
        maibot_aux.write_pid_file(maibot_aux.PID_FILE, proc.pid)  # no matching sidecar
        assert maibot_aux.current_managed_process() is None
    finally:
        proc.kill()


def test_stop_never_kills_unverified_pid(monkeypatch, tmp_path: Path):
    _patch_paths(monkeypatch, tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])  # noqa: S603
    try:
        maibot_aux.write_pid_file(maibot_aux.PID_FILE, proc.pid)
        maibot_aux.stop_maibot_aux()
        assert proc.poll() is None  # unrelated process untouched
    finally:
        proc.kill()
        proc.wait(timeout=5)


# ------------------------------------------------------------------ real spawn


async def test_real_spawn_env_is_clean(monkeypatch, tmp_path: Path):
    port = _free_port()
    instance = _make_instance(tmp_path / "inst", port=port)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("VIRTUAL_ENV", "/parent/venv")
    monkeypatch.setenv("PYTHONPATH", "/parent/path")
    monkeypatch.setenv("MAIBOT_WORKER_PROCESS", "1")
    monkeypatch.setenv("EULA_AGREE", "x")
    try:
        result = maibot_aux.start_maibot_aux(ready_timeout_s=10.0)
        assert result.rc == 0
        dump = json.loads((instance / "env_dump.json").read_text(encoding="utf-8"))
        assert dump["VIRTUAL_ENV"] is None
        assert dump["UV_PROJECT"] is None
        assert dump["PYTHONPATH"] is None
        assert dump["MAIBOT_WORKER_PROCESS"] is None
        assert dump["EULA_AGREE"] is None
        assert dump["MAIBOT_INSTANCE_DIR"] == str(instance)
        assert dump["PYTHONUNBUFFERED"] == "1"
        assert maibot_aux.current_managed_process() == result.spawned_pid
        maibot_aux.stop_maibot_aux()
        assert maibot_aux.maibot_aux_running() is False
    finally:
        pid = maibot_aux.read_pid_file(maibot_aux.PID_FILE)
        if pid is not None:
            maibot_aux._stop_owned_pid(pid)
        maibot_aux.clear_pid_file(maibot_aux.PID_FILE)


async def test_keyboard_interrupt_during_wait_leaves_no_process(monkeypatch, tmp_path: Path):
    port = _free_port()
    instance = _make_instance(tmp_path / "inst", port=port, bot_py="import time\nwhile True:\n    time.sleep(0.5)\n")
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    spawned: list[int] = []

    real_spawn = maibot_aux.spawn_detached

    def spawn(cmd, *, cwd, env=None, log_path=None, inherit_env=True):
        pid = real_spawn(cmd, cwd=cwd, env=env, log_path=log_path, inherit_env=inherit_env)
        spawned.append(pid)
        return pid

    monkeypatch.setattr(maibot_aux, "spawn_detached", spawn)

    calls = {"n": 0}

    def probe(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return False  # pre-spawn occupancy check: free
        raise KeyboardInterrupt

    monkeypatch.setattr(maibot_aux, "_port_connectable", probe)
    try:
        with pytest.raises(KeyboardInterrupt):
            maibot_aux.start_maibot_aux(ready_timeout_s=5.0)
        assert spawned
        assert maibot_aux.pid_alive(spawned[0]) is False
        assert maibot_aux.read_pid_file(maibot_aux.PID_FILE) is None
    finally:
        for pid in spawned:
            if maibot_aux.pid_alive(pid):
                maibot_aux._stop_owned_pid(pid, force=True)
        maibot_aux.clear_pid_file(maibot_aux.PID_FILE)


# ---------------------------------------------------------------- ownership hardening


def test_instance_dir_relative_and_symlink_are_canonicalized(monkeypatch, tmp_path: Path):
    real = _make_instance(tmp_path / "real", port=8000)
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setattr(
        maibot_aux,
        "repo_env_raw_value",
        lambda key: {
            "MAIBOT_MANAGED_ENABLED": "true",
            "MAIBOT_MANAGED_DIR": str(link),
        }.get(key),
    )
    config = maibot_aux.load_managed_config()
    assert config.instance_dir == real.resolve()

    monkeypatch.setattr(
        maibot_aux,
        "repo_env_raw_value",
        lambda key: {
            "MAIBOT_MANAGED_ENABLED": "true",
            "MAIBOT_MANAGED_DIR": "../real",
        }.get(key),
    )
    monkeypatch.setattr(maibot_aux, "PROJECT_ROOT", tmp_path / "sub")
    config = maibot_aux.load_managed_config()
    assert config.instance_dir == real.resolve()


def test_python_path_symlink_is_not_resolved(monkeypatch, tmp_path: Path):
    link = tmp_path / "python-link"
    link.symlink_to(sys.executable)
    monkeypatch.setattr(
        maibot_aux,
        "repo_env_raw_value",
        lambda key: {
            "MAIBOT_MANAGED_ENABLED": "true",
            "MAIBOT_MANAGED_DIR": str(tmp_path),
            "MAIBOT_MANAGED_PYTHON": str(link),
        }.get(key),
    )
    assert maibot_aux.load_managed_config().python == link


async def test_proc_unavailable_refuses_spawn(monkeypatch, tmp_path: Path):
    port = _free_port()
    instance = _make_instance(tmp_path / "inst", port=port)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(maibot_aux, "linux_managed_supported", lambda: False)
    spawned: list = []
    monkeypatch.setattr(maibot_aux, "spawn_detached", lambda *a, **k: spawned.append(1) or 1)
    assert maibot_aux.start_maibot_aux(ready_timeout_s=1.0).rc == 1
    assert spawned == []


def test_current_managed_process_requires_cwd(monkeypatch, tmp_path: Path):
    _patch_paths(monkeypatch, tmp_path)
    pid = os.getpid()
    monkeypatch.setattr(maibot_aux, "read_pid_file", lambda _p: pid)
    monkeypatch.setattr(maibot_aux, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(maibot_aux, "_proc_starttime", lambda _pid: "111")
    monkeypatch.setattr(maibot_aux, "_proc_boot_id", lambda: "boot")
    monkeypatch.setattr(
        maibot_aux,
        "_read_owner",
        lambda: {
            "pid": pid,
            "instance_dir": str(tmp_path),
            "starttime": "111",
            "boot_id": "boot",
        },
    )
    monkeypatch.setattr(maibot_aux, "linux_managed_supported", lambda: True)
    monkeypatch.setattr(maibot_aux, "_proc_cwd", lambda _pid: None)
    assert maibot_aux.current_managed_process() is None


async def test_identity_failure_after_spawn_rolls_back(monkeypatch, tmp_path: Path):
    port = _free_port()
    instance = _make_instance(tmp_path / "inst", port=port)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(maibot_aux, "current_managed_process", lambda: None)
    spawned: list[int] = []
    real_spawn = maibot_aux.spawn_detached

    def spawn(cmd, *, cwd, env=None, log_path=None, inherit_env=True):
        pid = real_spawn(cmd, cwd=cwd, env=env, log_path=log_path, inherit_env=inherit_env)
        spawned.append(pid)
        return pid

    monkeypatch.setattr(maibot_aux, "spawn_detached", spawn)
    try:
        result = maibot_aux.start_maibot_aux(ready_timeout_s=5.0)
        assert result.rc == 1
        assert maibot_aux.read_pid_file(maibot_aux.PID_FILE) is None
        assert spawned
        assert maibot_aux.pid_alive(spawned[0]) is False
    finally:
        for pid in spawned:
            if maibot_aux.pid_alive(pid):
                maibot_aux._stop_owned_pid(pid, force=True)
        maibot_aux.clear_pid_file(maibot_aux.PID_FILE)


async def test_sidecar_records_boot_id_and_starttime(monkeypatch, tmp_path: Path):
    port = _free_port()
    instance = _make_instance(tmp_path / "inst", port=port)
    _patch_env(monkeypatch, instance_dir=instance, python=sys.executable, bridge_url=f"ws://127.0.0.1:{port}/ws")
    _patch_paths(monkeypatch, tmp_path)
    try:
        result = maibot_aux.start_maibot_aux(ready_timeout_s=10.0)
        assert result.rc == 0
        owner = json.loads(maibot_aux.OWNER_FILE.read_text(encoding="utf-8"))
        assert owner["boot_id"] == maibot_aux._proc_boot_id()
        assert owner["starttime"]
        assert owner["instance_dir"] == str(instance.resolve())
    finally:
        pid = maibot_aux.read_pid_file(maibot_aux.PID_FILE)
        if pid is not None:
            maibot_aux._stop_owned_pid(pid, force=True)
        maibot_aux.clear_pid_file(maibot_aux.PID_FILE)


def test_stop_reports_unresolved_group_and_keeps_record(monkeypatch, tmp_path: Path):
    _patch_paths(monkeypatch, tmp_path)
    maibot_aux.write_pid_file(maibot_aux.PID_FILE, 555)
    monkeypatch.setattr(maibot_aux, "current_managed_process", lambda: 555)
    monkeypatch.setattr(maibot_aux, "_stop_owned_pid", lambda _pid, force=False: False)
    assert maibot_aux.stop_maibot_aux() is False
    assert maibot_aux.read_pid_file(maibot_aux.PID_FILE) == 555  # record kept


def test_stop_spawned_pid_returns_bool(monkeypatch, tmp_path: Path):
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(maibot_aux, "_stop_owned_pid", lambda _pid, force=False: False)
    assert maibot_aux.stop_spawned_pid(123) is False


def test_stop_reports_orphan_group_when_leader_dead(monkeypatch, tmp_path: Path):
    """leader 已退出（current_managed_process()==None）但同组仍有活成员：报未解决孤组、保留记录、不 kill。"""
    _patch_paths(monkeypatch, tmp_path)
    child = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-c",
            "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])",
        ],
        start_new_session=True,
    )
    try:
        child.wait(timeout=10)  # leader exits; grandchild stays in the same process group
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not process_util.group_has_live_member(child.pid):
            time.sleep(0.05)
        assert process_util.group_has_live_member(child.pid) is True

        maibot_aux.write_pid_file(maibot_aux.PID_FILE, child.pid)
        maibot_aux.OWNER_FILE.write_text(
            json.dumps({
                "pid": child.pid,
                "instance_dir": str(tmp_path),
                "starttime": "x",
                "boot_id": maibot_aux._proc_boot_id(),
            }),
            encoding="utf-8",
        )
        killed: list = []
        monkeypatch.setattr(maibot_aux, "_stop_owned_pid", lambda *a, **k: killed.append(1) or True)

        assert maibot_aux.current_managed_process() is None  # leader dead
        assert maibot_aux.stop_maibot_aux() is False
        assert killed == []  # never kills an unknown group
        assert maibot_aux.read_pid_file(maibot_aux.PID_FILE) == child.pid  # record kept
    finally:
        process_util.stop_pid(child.pid, force=True, wait_for_group=True)


def test_stop_clears_when_recorded_group_is_gone(monkeypatch, tmp_path: Path):
    _patch_paths(monkeypatch, tmp_path)
    maibot_aux.write_pid_file(maibot_aux.PID_FILE, os.getpid())  # our own pid, but no live orphan group recorded
    maibot_aux.OWNER_FILE.write_text(
        json.dumps({"pid": os.getpid(), "instance_dir": str(tmp_path), "starttime": "x", "boot_id": "stale"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(maibot_aux, "_stop_owned_pid", lambda *a, **k: (_ for _ in ()).throw(AssertionError("kill")))
    # stale boot_id -> not an orphan; nothing running -> clear
    monkeypatch.setattr(maibot_aux, "maibot_aux_running", lambda: False)
    assert maibot_aux.stop_maibot_aux() is True
    assert maibot_aux.read_pid_file(maibot_aux.PID_FILE) is None
