from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config


def build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_plugin_reload_api_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.plugin_reload.reload_ops.execute_plugin_reload",
        lambda name: {
            "plugin": name,
            "reload_policy": "metadata",
            "action": "metadata-reload",
            "ok": True,
            "message": "ok",
        },
    )

    client = build_client(monkeypatch)
    response = client.post("/pallas/api/plugins/help/reload")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["ok"] is True
    assert payload["action"] == "metadata-reload"


def test_plugin_reload_api_partial_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.plugin_reload.reload_ops.execute_plugin_reload",
        lambda name: {
            "plugin": name,
            "reload_policy": "full",
            "action": "metadata-only",
            "ok": False,
            "message": "need restart",
        },
    )

    client = build_client(monkeypatch)
    response = client.post("/pallas/api/plugins/help/reload")
    assert response.status_code == 409
    assert response.json()["ok"] is False
