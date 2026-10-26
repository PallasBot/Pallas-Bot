import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE = REPO_ROOT / "tools/experiments/maibot_spike/message_protocol.py"


def test_maim_message_loopback_probe_exits_cleanly() -> None:
    python = Path(os.environ.get("MAIM_MESSAGE_PYTHON", "/tmp/opencode/maim068/venv/bin/python"))
    if not python.is_file():
        pytest.skip(
            "maim-message probe environment missing; create an isolated env with "
            "maim-message==0.6.8 and set MAIM_MESSAGE_PYTHON"
        )

    try:
        result = subprocess.run(
            [str(python), str(PROBE)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=12,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        if "client -> server payload:" not in stdout or "server -> client payload:" not in stdout:
            pytest.fail(f"probe timed out before proving bidirectional payloads:\n{stdout}\n{stderr}")
        assert '"account_id": "synthetic-account"' in stdout
        assert '"scope": "probe"' in stdout
        assert "synthetic-group" in stdout
        assert "synthetic-user" in stdout
        if "shutdown snapshot:" not in stdout or "('asyncio_0', False)" not in stdout:
            pytest.fail(f"probe timed out without identifying its remaining worker thread:\n{stdout}\n{stderr}")
        evidence = "\n".join(
            line
            for line in stdout.splitlines()
            if "payload:" in line or "send result:" in line or "shutdown snapshot:" in line
        )
        pytest.fail(f"all loopback assertions ran, but maim-message did not exit naturally within 12s:\n{evidence}")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "PROTOCOL PROBE PASSED" in output
    assert "not a MaiBot product integration" in output
