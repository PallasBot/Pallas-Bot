"""Loopback-only Pallas control API child used by lifecycle tests."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

started = time.monotonic()
stopping = False
quiesced = False
api_announced = False
event_path = Path(os.environ["MANAGED_FIXTURE_EVENTS"])
connection_path = Path(os.environ["MANAGED_FIXTURE_CONNECTION"])


def record(name: str) -> None:
    with event_path.open("a", encoding="utf-8") as stream:
        stream.write(name + "\n")


def stop(_signum, _frame) -> None:
    global stopping
    record("pallas-sigterm")
    stopping = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self) -> bool:
        if self.headers.get("X-Pallas-Internal-Token") == "fixture-control-token":
            return True
        self.send_json({"ok": False}, 403)
        return False

    def do_GET(self) -> None:
        global api_announced
        if not self.authenticated():
            return
        if self.path != "/pallas/api/internal/maibot/control/status":
            self.send_json({"ok": False}, 404)
            return
        record("status")
        api_ready = time.monotonic() - started >= float(os.environ.get("MANAGED_FIXTURE_API_DELAY", "0"))
        if api_ready and not api_announced:
            api_announced = True
            record("api-ready")
        try:
            connection = json.loads(connection_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            connection = {}
        connected = connection.get("connected") is True
        status = {
            "ok": True,
            "runtime_id": os.environ["MANAGED_FIXTURE_RUNTIME_ID"],
            "contract": "maibot-native-control-v1",
            "control_ready": api_ready,
            "bridge_status": {"connected": connected, "state": "connected" if connected else "offline"},
            "component_ready": api_ready and connected and not quiesced,
            "complete_ready": False,
            "readiness_scope": "managed-component",
            "model_invocation_verified": False,
            "quiesced": quiesced,
        }
        self.send_json(status)

    def do_POST(self) -> None:
        global quiesced
        if not self.authenticated():
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/pallas/api/internal/maibot/control/quiesce":
            if body:
                self.send_json({"ok": False}, 400)
                return
            quiesced = True
            record("quiesce")
            self.send_json({"ok": True, "quiesced": True})
            return
        self.send_json({"ok": False}, 404)


server = HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler)
server.timeout = 0.1
print("fixture-pallas-output", flush=True)
fixture_exit = False
while not stopping:
    exit_after = float(os.environ.get("MANAGED_FIXTURE_EXIT_AFTER", "0"))
    if exit_after and time.monotonic() - started >= exit_after:
        record("pallas-exit")
        fixture_exit = True
        break
    server.handle_request()
server.server_close()
if fixture_exit:
    raise SystemExit(int(os.environ.get("MANAGED_FIXTURE_EXIT_CODE", "23")))
