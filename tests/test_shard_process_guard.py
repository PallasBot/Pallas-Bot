from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts" / "shard_process_guard.py"


def load_guard_module():
    spec = importlib.util.spec_from_file_location("shard_process_guard", GUARD)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repo_python_script_pids_matches_fake_hub_in_tmp_repo(tmp_path: Path) -> None:
    guard = load_guard_module()
    (tmp_path / "bot_hub.py").write_text("import time\nwhile True:\n    time.sleep(1)\n", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "bot_hub.py"], cwd=tmp_path)
    try:
        time.sleep(0.2)
        pids = guard.repo_python_script_pids(tmp_path, "bot_hub.py")
        assert proc.pid in pids
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_tcp_listen_pids_detects_listener() -> None:
    guard = load_guard_module()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        pids = guard.tcp_listen_pids(port)
        assert pids
    finally:
        sock.close()


def test_cli_list_mode() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(GUARD),
            "--repo",
            str(REPO_ROOT),
            "--script",
            "bot_hub.py",
            "--list",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
