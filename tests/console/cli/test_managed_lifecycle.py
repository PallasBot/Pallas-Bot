"""Bounded Pallas/MaiBot managed lifecycle contracts."""

from __future__ import annotations

import copy
import json
import os
import select
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from pallas.console.cli import managed_lifecycle


def _status(*, mai_pid: int | None = None) -> dict:
    return {
        "ok": True,
        "runtime_id": "fixture-runtime-1",
        "contract": "maibot-native-control-v1",
        "control_ready": True,
        "bridge_status": {"connected": True, "state": "connected"},
        "component_ready": True,
        "complete_ready": False,
        "readiness_scope": "managed-component",
        "model_invocation_verified": False,
        "quiesced": False,
    }


def test_status_requires_component_contract_and_owned_process(monkeypatch) -> None:
    monkeypatch.setattr(managed_lifecycle.maibot_aux, "current_managed_process", lambda: os.getpid())
    status = _status(mai_pid=os.getpid())
    assert managed_lifecycle.component_ready(status, expected_runtime_id="fixture-runtime-1", mai_pid=os.getpid())

    invalid: list[dict] = []
    for key, value in (
        ("control_ready", False),
        ("contract", "old"),
        ("runtime_id", "old-runtime"),
        ("component_ready", False),
        ("quiesced", True),
        ("model_invocation_verified", True),
        ("complete_ready", True),
    ):
        candidate = copy.deepcopy(status)
        candidate[key] = value
        invalid.append(candidate)

    assert all(
        not managed_lifecycle.component_ready(
            candidate,
            expected_runtime_id="fixture-runtime-1",
            mai_pid=os.getpid(),
        )
        for candidate in invalid
    )
    disconnected = copy.deepcopy(status)
    disconnected["bridge_status"]["connected"] = False
    assert not managed_lifecycle.component_ready(
        disconnected,
        expected_runtime_id="fixture-runtime-1",
        mai_pid=os.getpid(),
    )
    monkeypatch.setattr(managed_lifecycle.maibot_aux, "current_managed_process", lambda: None)
    assert not managed_lifecycle.component_ready(status, expected_runtime_id="fixture-runtime-1", mai_pid=os.getpid())


def test_start_failure_rolls_back_only_aux_started_by_this_call(monkeypatch, tmp_path: Path) -> None:
    paths = managed_lifecycle.ManagedPaths(
        project_root=tmp_path,
        run_dir=tmp_path / "run",
        pid_file=tmp_path / "run" / "bot.pid",
        owner_file=tmp_path / "run" / "bot.owner.json",
        lock_file=tmp_path / "run" / "managed.lock",
        log_file=tmp_path / "logs" / "bot.log",
    )
    monkeypatch.setattr(
        managed_lifecycle,
        "_preflight",
        lambda *_a: (object(), SimpleNamespace(platform="pallas-qq"), "control"),
    )
    monkeypatch.setattr(managed_lifecycle, "_port_available", lambda _port: True)
    monkeypatch.setattr(managed_lifecycle, "_start_aux_tracked", lambda: (True, ("work",)))
    monkeypatch.setattr(
        managed_lifecycle, "_spawn_pallas", lambda *_a, **_k: (_ for _ in ()).throw(OSError("fixture spawn failure"))
    )
    stopped: list[tuple[str, ...]] = []
    monkeypatch.setattr(managed_lifecycle, "_stop_aux_names", lambda names: stopped.append(names) or True)

    result = managed_lifecycle.start_managed_runtime(
        19090,
        paths=paths,
        detached=True,
        stop_requested=lambda: False,
    )
    assert result is None
    assert stopped == [("work",)]


def test_preflight_refuses_an_external_pallas_api_listener(monkeypatch, tmp_path: Path) -> None:
    from pallas.console.cli import maibot_aux

    config = maibot_aux.ManagedMaiBotConfig(enabled=True, instance_dir=tmp_path, python=Path(sys.executable))
    monkeypatch.setattr(maibot_aux, "load_managed_config", lambda: config)
    monkeypatch.setattr(maibot_aux, "linux_managed_supported", lambda: True)
    monkeypatch.setattr(maibot_aux, "_port_connectable", lambda *_a: True)
    monkeypatch.setattr(managed_lifecycle, "read_pid_file", lambda _path: None)
    monkeypatch.setattr(managed_lifecycle, "_read_owner", lambda _paths: None)

    with pytest.raises(managed_lifecycle.ManagedLifecycleError, match="端口已被占用"):
        managed_lifecycle._preflight(managed_lifecycle.ManagedPaths(project_root=tmp_path), 19090)


def test_mai_stop_failure_keeps_pallas_and_records(monkeypatch, tmp_path: Path) -> None:
    paths = managed_lifecycle.ManagedPaths(
        project_root=tmp_path,
        run_dir=tmp_path / "run",
        pid_file=tmp_path / "run" / "bot.pid",
        owner_file=tmp_path / "run" / "bot.owner.json",
        lock_file=tmp_path / "run" / "managed.lock",
        log_file=tmp_path / "logs" / "bot.log",
    )
    paths.run_dir.mkdir(parents=True)
    paths.pid_file.write_text("34567\n", encoding="utf-8")
    owner = {"pid": 34567, "runtime_id": "fixture-runtime-1", "mai_pid": 45678, "mai_owner": {"pid": 45678}}
    paths.owner_file.write_text(json.dumps(owner), encoding="utf-8")
    monkeypatch.setattr(managed_lifecycle, "_owner_matches", lambda *_a: True)
    monkeypatch.setattr(managed_lifecycle, "_control_status", lambda *_a: _status())
    control_calls: list[str] = []
    monkeypatch.setattr(
        managed_lifecycle,
        "control_request",
        lambda _port, method, path, **_kwargs: control_calls.append(path) or {"ok": True, "quiesced": True},
    )
    from pallas.console.cli import maibot_aux

    monkeypatch.setattr(maibot_aux, "current_managed_process", lambda: 45678)
    monkeypatch.setattr(maibot_aux, "stop_spawned_pid", lambda _pid, **_kw: False)
    stopped_pallas: list[int] = []
    monkeypatch.setattr(managed_lifecycle, "_stop_process", lambda pid, _proc=None: stopped_pallas.append(pid) or True)

    result = managed_lifecycle._shutdown_locked(
        paths,
        pid=34567,
        owner=owner,
        port=19090,
        runtime_id="fixture-runtime-1",
        mai_pid=45678,
        control_token="fixture-control-token",
        process=None,
        aux_started=(),
        stop_aux_all=False,
        stop_mai=True,
    )
    assert result is False
    assert control_calls == [managed_lifecycle.CONTROL_QUIESCE]
    assert stopped_pallas == []
    assert paths.pid_file.read_text(encoding="utf-8") == "34567\n"
    assert json.loads(paths.owner_file.read_text(encoding="utf-8")) == owner


def test_shutdown_never_quiesces_a_different_runtime(monkeypatch, tmp_path: Path) -> None:
    paths = managed_lifecycle.ManagedPaths(
        project_root=tmp_path,
        run_dir=tmp_path / "run",
        pid_file=tmp_path / "run" / "bot.pid",
        owner_file=tmp_path / "run" / "bot.owner.json",
        lock_file=tmp_path / "run" / "managed.lock",
        log_file=tmp_path / "logs" / "bot.log",
    )
    paths.run_dir.mkdir(parents=True)
    paths.pid_file.write_text("34567\n", encoding="utf-8")
    owner = {"pid": 34567, "runtime_id": "fixture-runtime-1"}
    paths.owner_file.write_text(json.dumps(owner), encoding="utf-8")
    monkeypatch.setattr(managed_lifecycle, "_owner_matches", lambda *_a: True)
    monkeypatch.setattr(managed_lifecycle, "_control_status", lambda *_a: _status() | {"runtime_id": "other-runtime"})
    calls: list[str] = []
    monkeypatch.setattr(
        managed_lifecycle,
        "control_request",
        lambda _port, _method, path, **_kwargs: calls.append(path) or {"ok": True, "drained": True},
    )
    from pallas.console.cli import maibot_aux

    monkeypatch.setattr(maibot_aux, "current_managed_process", lambda: None)
    monkeypatch.setattr(maibot_aux, "maibot_aux_running", lambda: False)
    monkeypatch.setattr(managed_lifecycle, "_stop_process", lambda *_a: True)

    result = managed_lifecycle._shutdown_locked(
        paths,
        pid=34567,
        owner=owner,
        port=19090,
        runtime_id="fixture-runtime-1",
        mai_pid=None,
        control_token="fixture-control-token",
        process=None,
        aux_started=(),
        stop_aux_all=False,
        stop_mai=True,
    )
    assert result is False
    assert calls == []


def test_repeated_managed_stop_without_records_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    paths = managed_lifecycle.ManagedPaths(
        project_root=tmp_path,
        run_dir=tmp_path / "run",
        pid_file=tmp_path / "run" / "bot.pid",
        owner_file=tmp_path / "run" / "bot.owner.json",
        lock_file=tmp_path / "run" / "managed.lock",
        log_file=tmp_path / "logs" / "bot.log",
    )
    from pallas.console.cli import maibot_aux, unified_lifecycle

    monkeypatch.setattr(maibot_aux, "current_managed_process", lambda: None)
    monkeypatch.setattr(maibot_aux, "maibot_aux_running", lambda: False)
    monkeypatch.setattr(maibot_aux, "stop_maibot_aux", lambda: True)
    monkeypatch.setattr(unified_lifecycle, "stop_aux_services", lambda: None)
    assert managed_lifecycle.stop_running_managed(19090, paths=paths) is True


def test_start_owner_write_failure_still_reaps_its_direct_child(monkeypatch, tmp_path: Path) -> None:
    paths = managed_lifecycle.ManagedPaths(
        project_root=tmp_path,
        pid_file=tmp_path / "run" / "bot.pid",
        owner_file=tmp_path / "run" / "bot.owner.json",
        lock_file=tmp_path / "run" / "managed.lock",
    )
    process = SimpleNamespace(pid=34567, poll=lambda: None)
    monkeypatch.setattr(managed_lifecycle, "_preflight", lambda *_a: (object(), object(), "control"))
    monkeypatch.setattr(managed_lifecycle, "_port_available", lambda _port: True)
    monkeypatch.setattr(managed_lifecycle, "_start_aux_tracked", lambda: (True, ()))
    monkeypatch.setattr(managed_lifecycle, "_spawn_pallas", lambda *_a, **_k: process)
    monkeypatch.setattr(managed_lifecycle, "_write_owner", lambda *_a: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(managed_lifecycle, "_owner_matches", lambda *_a: False)
    monkeypatch.setattr(managed_lifecycle, "pid_alive", lambda _pid: True)
    reaped = []
    monkeypatch.setattr(managed_lifecycle, "_stop_process", lambda pid, proc: reaped.append((pid, proc)) or True)
    assert (
        managed_lifecycle.start_managed_runtime(19090, paths=paths, detached=True, stop_requested=lambda: False) is None
    )
    assert reaped == [(34567, process)]


def test_dead_pallas_can_finalize_owned_mai_and_allow_restart(monkeypatch, tmp_path: Path) -> None:
    paths = managed_lifecycle.ManagedPaths(
        project_root=tmp_path,
        pid_file=tmp_path / "bot.pid",
        owner_file=tmp_path / "bot.owner.json",
    )
    owner = {"pid": 34567, "runtime_id": "fixture-runtime-1", "mai_pid": 45678, "mai_owner": {"pid": 45678}}
    paths.pid_file.write_text("34567\n", encoding="utf-8")
    paths.owner_file.write_text(json.dumps(owner), encoding="utf-8")
    monkeypatch.setattr(managed_lifecycle, "_owner_matches", lambda *_a: False)
    monkeypatch.setattr(managed_lifecycle, "pid_alive", lambda _pid: False)
    monkeypatch.setattr(managed_lifecycle.maibot_aux, "current_managed_process", lambda: 45678)
    stopped = []
    monkeypatch.setattr(
        managed_lifecycle.maibot_aux, "stop_spawned_pid", lambda pid, **_kw: stopped.append(pid) or True
    )
    assert (
        managed_lifecycle._shutdown_locked(
            paths,
            pid=34567,
            owner=owner,
            port=19090,
            runtime_id="fixture-runtime-1",
            mai_pid=45678,
            control_token="control",
            process=None,
            aux_started=(),
            stop_aux_all=False,
            stop_mai=True,
        )
        is True
    )
    assert stopped == [45678]
    assert not paths.pid_file.exists()
    assert not paths.owner_file.exists()


def test_persistent_stop_does_not_adopt_mai_without_paired_owner(monkeypatch, tmp_path: Path):
    paths = managed_lifecycle.ManagedPaths(
        project_root=tmp_path,
        pid_file=tmp_path / "bot.pid",
        owner_file=tmp_path / "owner.json",
        lock_file=tmp_path / "managed.lock",
    )
    paths.pid_file.write_text("34567\n", encoding="utf-8")
    monkeypatch.setattr(managed_lifecycle, "pid_alive", lambda _pid: False)
    monkeypatch.setattr(managed_lifecycle.maibot_aux, "current_managed_process", lambda: 45678)
    monkeypatch.setattr(managed_lifecycle.maibot_aux, "stop_spawned_pid", lambda *_a, **_k: pytest.fail("unpaired Mai"))
    assert managed_lifecycle.stop_running_managed(19090, paths=paths) is False
    assert paths.pid_file.exists()


def test_dead_pallas_leader_with_live_group_is_not_reported_stopped(monkeypatch):
    monkeypatch.setattr(managed_lifecycle, "pid_alive", lambda _pid: False)
    monkeypatch.setattr(managed_lifecycle, "group_has_live_member", lambda _pgid: True)
    monkeypatch.setattr(managed_lifecycle, "stop_pid", lambda *_a, **_k: pytest.fail("unverified orphan group"))
    assert managed_lifecycle._stop_process(34567) is False


def test_cancelled_transport_wait_returns_without_sleep(monkeypatch) -> None:
    from pallas.console.cli import maibot_aux

    monkeypatch.setattr(maibot_aux.time, "sleep", lambda _delay: pytest.fail("cancel wait slept"))
    assert (
        maibot_aux._wait_transport_ready("127.0.0.1", 1, timeout_s=60, owned_pid=None, stop_requested=lambda: True) == 1
    )


def test_control_request_is_loopback_direct_and_does_not_follow_redirect(monkeypatch) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    responses: list[tuple[str, str | None]] = []

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            responses.append((self.path, self.headers.get("X-Pallas-Internal-Token")))
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/redirect-target")
            self.end_headers()

        def log_message(self, _format: str, *_args) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    try:
        result = managed_lifecycle.control_request(
            server.server_port,
            "GET",
            "/pallas/api/internal/maibot/control/status",
            token="fixture-control-token",
            timeout_s=0.5,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert result is None
    assert responses == [("/pallas/api/internal/maibot/control/status", "fixture-control-token")]


def _launch_fixture(
    tmp_path: Path,
    *,
    api_delay: str,
    exit_after: str,
    detached: bool = False,
) -> tuple[subprocess.Popen, bytearray, Path]:
    fixture_dir = Path(__file__).parent / "fixtures"
    project = tmp_path / "pallas-project"
    project.mkdir()
    events = tmp_path / "events.log"
    connection = tmp_path / "connection.json"
    project.joinpath("bot.py").write_text(
        "import os, runpy\nrunpy.run_path(os.environ['MANAGED_FIXTURE_PALLAS_SCRIPT'], run_name='__main__')\n",
        encoding="utf-8",
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
        "PORT": str(port),
        "MANAGED_FIXTURE_PROJECT": str(project),
        "MANAGED_FIXTURE_EVENTS": str(events),
        "MANAGED_FIXTURE_CONNECTION": str(connection),
        "MANAGED_FIXTURE_RUNTIME_ID": "fixture-runtime-1",
        "MANAGED_FIXTURE_PALLAS_SCRIPT": str(fixture_dir / "managed_pallas_http.py"),
        "MANAGED_FIXTURE_MAI_SCRIPT": str(fixture_dir / "managed_mai_child.py"),
        "MANAGED_FIXTURE_API_DELAY": api_delay,
        "MANAGED_FIXTURE_EXIT_AFTER": exit_after,
        "MANAGED_FIXTURE_EXIT_CODE": "23",
        "MANAGED_FIXTURE_DETACH": "1" if detached else "0",
    }
    proc = subprocess.Popen(
        [sys.executable, "-u", str(fixture_dir / "managed_launcher_driver.py")],
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        start_new_session=True,
    )
    assert proc.stdout is not None
    return proc, bytearray(), events


def _read_until(proc: subprocess.Popen, output: bytearray, marker: str, timeout_s: float = 15) -> None:
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout_s
    encoded_marker = marker.encode()
    while encoded_marker not in output:
        remaining = deadline - time.monotonic()
        assert remaining > 0 and proc.poll() is None, output.decode(errors="replace")
        readable, _, _ = select.select([proc.stdout], [], [], min(0.2, remaining))
        if readable:
            output.extend(os.read(proc.stdout.fileno(), 4096))


@pytest.mark.parametrize(
    ("received", "expected", "exit_after"),
    ((signal.SIGINT, 130, "0"), (signal.SIGTERM, 143, "0"), (None, 23, "3")),
)
def test_foreground_managed_signal_uses_fixture_api_and_ordered_stop(
    tmp_path: Path,
    received: signal.Signals | None,
    expected: int,
    exit_after: str,
) -> None:
    proc, output, events = _launch_fixture(tmp_path, api_delay="0.4", exit_after=exit_after)
    try:
        _read_until(proc, output, "unified 前台运行")
        if received is not None:
            proc.send_signal(received)
        rest, _ = proc.communicate(timeout=15)
        output.extend(rest or b"")
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=10)

    assert proc.returncode == expected, output.decode(errors="replace")
    text = output.decode(errors="replace")
    assert "fixture-pallas-output" in text
    assert "fixture-maibot-output" in text
    assert "未验证真实模型调用" in text
    sequence = events.read_text(encoding="utf-8").splitlines()
    assert sequence.index("api-ready") < sequence.index("mai-start-request")
    if received is None:
        assert "pallas-exit" in sequence
        assert sequence.index("pallas-exit") < sequence.index("mai-stop")
    else:
        assert sequence.index("quiesce") < sequence.index("control-ready-at-mai-stop")
        assert sequence.index("control-ready-at-mai-stop") < sequence.index("mai-stop")
        assert sequence.index("mai-stop") < sequence.index("pallas-sigterm")
        assert sequence.index("pallas-sigterm") < sequence.index("aux-stop")


def test_foreground_signal_cancels_pallas_api_wait_before_starting_mai(tmp_path: Path) -> None:
    proc, output, events = _launch_fixture(tmp_path, api_delay="30", exit_after="0")
    started = time.monotonic()
    try:
        _read_until(proc, output, "fixture-pallas-output")
        proc.send_signal(signal.SIGINT)
        rest, _ = proc.communicate(timeout=8)
        output.extend(rest or b"")
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=8)

    assert proc.returncode == 130
    assert time.monotonic() - started < 8
    sequence = events.read_text(encoding="utf-8").splitlines()
    assert "api-ready" not in sequence
    assert "mai-start-request" not in sequence
    assert "pallas-sigterm" in sequence


def test_detached_start_returns_only_after_component_ready_and_logs_child_output(tmp_path: Path) -> None:
    proc, output, events = _launch_fixture(tmp_path, api_delay="0.4", exit_after="0", detached=True)
    rest, _ = proc.communicate(timeout=15)
    output.extend(rest or b"")
    text = output.decode(errors="replace")
    assert proc.returncode == 0, text
    assert "MaiBot 托管组件就绪" in text
    assert "unified 已转入后台" in text
    assert "fixture-pallas-output" not in text
    logs = list((tmp_path / "pallas-project" / "logs").glob("bot_*.log"))
    assert len(logs) == 1 and "fixture-pallas-output" in logs[0].read_text(encoding="utf-8")
    sequence = events.read_text(encoding="utf-8").splitlines()
    assert sequence.index("api-ready") < sequence.index("mai-start-request")
    assert sequence.index("quiesce") < sequence.index("mai-stop") < sequence.index("pallas-sigterm")
    assert sequence.index("pallas-sigterm") < sequence.index("aux-stop")
