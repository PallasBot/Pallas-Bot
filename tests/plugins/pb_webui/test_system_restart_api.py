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


def test_system_restart_schedules_full_restart(monkeypatch) -> None:
    calls: list[bool] = []

    monkeypatch.setattr(mod, "_bot_restart_available", lambda: True)
    monkeypatch.setattr(
        "pallas.console.cli.bot_process.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.runtime_mode.resolve_bot_mode",
        lambda mode="auto": "unified",
    )
    monkeypatch.setattr(
        "pallas.console.cli.bot_process.schedule_bot_restart",
        lambda *, workers_only=False, **kwargs: calls.append(workers_only) or True,
    )

    client = build_client(monkeypatch)
    response = client.post("/pallas/api/system/restart", json={"workers_only": False})
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["scheduled"] is True
    assert payload["mode"] == "full-restart"
    assert calls == [False]


def test_system_restart_rejects_workers_only_on_unified(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.cli.bot_process.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.runtime_mode.resolve_bot_mode",
        lambda mode="auto": "unified",
    )

    client = build_client(monkeypatch)
    response = client.post("/pallas/api/system/restart", json={"workers_only": True})
    assert response.status_code == 400


def test_system_restart_unavailable_when_lifecycle_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.cli.bot_process.bot_lifecycle_available",
        lambda: False,
    )

    client = build_client(monkeypatch)
    response = client.post("/pallas/api/system/restart", json={"workers_only": False})
    assert response.status_code == 503
