"""SSE 日志 Last-Event-ID 断点续传。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    monkeypatch.setattr(mod, "_ensure_log_sink", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_logs_stream_accepts_last_event_id_query(monkeypatch) -> None:
    events = [
        'id: 1\ndata: {"id":1,"level":"info","message":"a"}\n\n',
        'id: 2\ndata: {"id":2,"level":"info","message":"b"}\n\n',
    ]

    def fake_iter(_scope, *, source=None, last_event_id=None):
        _ = source
        start = int(last_event_id or 0)
        for chunk in events:
            if chunk.startswith("id: "):
                eid = int(chunk.split("\n", 1)[0].removeprefix("id: ").strip())
                if eid <= start:
                    continue
            yield chunk

    monkeypatch.setattr("pallas.console.web.iter_nonebot_log_sse", fake_iter)
    client = _build_client(monkeypatch)
    with client.stream("GET", "/pallas/api/logs/stream", params={"last_event_id": 1}) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "id: 2" in body
    assert "id: 1" not in body.split("id: 2")[0]


def test_logs_stream_accepts_last_event_id_header(monkeypatch) -> None:
    captured: list[int | None] = []

    def fake_iter(_scope, *, source=None, last_event_id=None):
        _ = source
        captured.append(last_event_id)
        yield "id: 1\ndata: {}\n\n"

    monkeypatch.setattr("pallas.console.web.iter_nonebot_log_sse", fake_iter)
    client = _build_client(monkeypatch)
    with client.stream("GET", "/pallas/api/logs/stream", headers={"Last-Event-ID": "42"}) as response:
        assert response.status_code == 200
        next(response.iter_text(), "")
    assert captured == [42]
