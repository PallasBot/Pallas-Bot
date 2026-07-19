from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config(), enable_runtime_hooks=False)
    return TestClient(app)


def test_help_preview_route_registered(monkeypatch) -> None:
    async def fake_render(**_kwargs) -> bytes:
        return b"\x89PNG\r\n\x1a\n"

    monkeypatch.setattr("packages.help.preview.render_help_preview_bytes", fake_render)
    client = _build_client(monkeypatch)
    resp = client.get("/pallas/api/help/preview?level=menu")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("image/png")
    assert resp.content.startswith(b"\x89PNG")
