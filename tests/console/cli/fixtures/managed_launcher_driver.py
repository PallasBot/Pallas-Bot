"""Runs the public foreground managed path against loopback fixture children."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pallas.console.cli import maibot_aux, managed_lifecycle, unified_lifecycle

project = Path(os.environ["MANAGED_FIXTURE_PROJECT"])
events = Path(os.environ["MANAGED_FIXTURE_EVENTS"])
mai_script = Path(os.environ["MANAGED_FIXTURE_MAI_SCRIPT"])
port = int(os.environ["PORT"])
config = maibot_aux.ManagedMaiBotConfig(enabled=True, instance_dir=project, python=Path(sys.executable))
bridge = SimpleNamespace(enabled=True, platform="pallas-qq", url="ws://127.0.0.1:8000/ws", token="fixture-only")
mai_process: subprocess.Popen | None = None


def record(name: str) -> None:
    with events.open("a", encoding="utf-8") as stream:
        stream.write(name + "\n")


def current_mai() -> int | None:
    return mai_process.pid if mai_process is not None and mai_process.poll() is None else None


def start_mai(**_kwargs):
    global mai_process
    if "api-ready" not in events.read_text(encoding="utf-8"):
        return maibot_aux.ManagedStartResult(rc=1)
    record("mai-start-request")
    mai_process = subprocess.Popen(
        [sys.executable, str(mai_script)],
        cwd=project,
        env=os.environ.copy(),
        start_new_session=True,
    )
    return maibot_aux.ManagedStartResult(
        rc=0,
        spawned_pid=mai_process.pid,
        owner={"pid": mai_process.pid, "starttime": maibot_aux._proc_starttime(mai_process.pid)},
    )


def stop_mai(pid: int, *, expected_owner: dict) -> bool:
    if mai_process is None:
        return True
    if pid != mai_process.pid:
        return False
    if expected_owner != {"pid": pid, "starttime": maibot_aux._proc_starttime(pid)}:
        return False
    status = managed_lifecycle.control_request(
        port,
        "GET",
        managed_lifecycle.CONTROL_STATUS,
        token="fixture-control-token",
    )
    if isinstance(status, dict) and status.get("control_ready") is True and status.get("quiesced") is True:
        record("control-ready-at-mai-stop")
    if mai_process.poll() is None:
        mai_process.terminate()
        try:
            mai_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return False
    record("mai-stop")
    return True


def stop_aux() -> bool:
    record("aux-stop")
    return True


with ExitStack() as stack:
    replacements = (
        (maibot_aux, "load_managed_config", lambda: config),
        (maibot_aux, "linux_managed_supported", lambda: True),
        (maibot_aux, "_load_bridge", lambda: (bridge, None)),
        (maibot_aux, "_validate_static_instance", lambda *_a, **_k: ([], {})),
        (maibot_aux, "_port_connectable", lambda *_a, **_k: False),
        (maibot_aux, "current_managed_process", current_mai),
        (maibot_aux, "maibot_aux_running", lambda: current_mai() is not None),
        (maibot_aux, "start_maibot_aux", start_mai),
        (maibot_aux, "stop_spawned_pid", stop_mai),
        (
            managed_lifecycle,
            "derive_internal_token",
            lambda purpose: "fixture-control-token" if purpose == "maibot-control-v1" else "",
        ),
        (managed_lifecycle, "_start_aux_tracked", lambda: (True, ("embed",))),
        (managed_lifecycle, "_stop_aux_names", lambda names: stop_aux()),
        (unified_lifecycle, "PROJECT_ROOT", project),
        (unified_lifecycle, "RUN_DIR", project / "run"),
        (unified_lifecycle, "LOG_DIR", project / "logs"),
        (unified_lifecycle, "PID_FILE", project / "run" / "bot.pid"),
        (unified_lifecycle, "LOG_FILE", project / "logs" / "bot.log"),
        (unified_lifecycle, "read_listen_port", lambda: port),
        (unified_lifecycle, "prepare_unified_ports", lambda *_a, **_k: 0),
        (unified_lifecycle, "stop_aux_services", stop_aux),
    )
    for target, name, value in replacements:
        stack.enter_context(patch.object(target, name, value))
    detached = os.environ.get("MANAGED_FIXTURE_DETACH") == "1"
    rc = unified_lifecycle.start_bot(detach=detached)
    if detached and rc == 0:
        rc = unified_lifecycle.stop_bot()
    raise SystemExit(rc)
