from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_plugin_bundled_readme_returns_core_plugin_doc(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/help/readme")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "bundled"
    assert payload["relative_path"] == "docs/plugins/help/README.md"
    assert "牛牛帮助" in payload["markdown"]
    help_cover = Path(__file__).resolve().parents[3] / "packages" / "help" / "assets" / "cover.png"
    if help_cover.is_file():
        assert "/pallas/plugin-assets/help/assets/cover.png" in payload["markdown"]
        assert "brand-avatar" not in payload["markdown"]


def test_plugin_bundled_readme_uses_drink_cover_when_present(monkeypatch) -> None:
    drink_cover = Path(__file__).resolve().parents[3] / "packages" / "drink" / "assets" / "cover.png"
    if not drink_cover.is_file():
        return
    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/drink/readme")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert "/pallas/plugin-assets/drink/assets/cover.png" in payload["markdown"]
    assert "brand-avatar" not in payload["markdown"]


def test_plugin_bundled_readme_maps_official_extension_package(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/draw/readme")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["relative_path"] == "docs/plugins/draw/README.md"
    assert "牛牛画画" in payload["markdown"]


def test_plugin_bundled_readme_unknown_plugin_404(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/not-a-real-plugin-id/readme")
    assert response.status_code == 404
