"""Tiny MaiBot/host process tree for Linux ownership and shutdown tests."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

connection_path = Path(os.environ["MANAGED_FIXTURE_CONNECTION"])
event_path = Path(os.environ["MANAGED_FIXTURE_EVENTS"])
stopping = False


def record(name: str) -> None:
    with event_path.open("a", encoding="utf-8") as stream:
        stream.write(name + "\n")


if len(sys.argv) > 1 and sys.argv[1] == "host":
    print("fixture-maibot-host-output", flush=True)
    while True:
        time.sleep(1)


host = subprocess.Popen([sys.executable, __file__, "host"])
connection_path.write_text(
    json.dumps({"connected": True}),
    encoding="utf-8",
)
record("mai-process-started")


def stop(_signum, _frame) -> None:
    global stopping
    stopping = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
print("fixture-maibot-output", flush=True)
while not stopping:
    time.sleep(0.1)
connection_path.write_text(json.dumps({"connected": False}), encoding="utf-8")
host.terminate()
host.wait(timeout=3)
record("mai-process-stopped")
