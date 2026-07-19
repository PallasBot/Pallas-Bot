from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config
from pallas.core.shared.service_probe import ServiceProbeResult


def test_connectivity_check_returns_runtime_fields(monkeypatch) -> None:
    async def fake_probe_all_connectivity_from_draft(values):
        _ = values
        return [
            ServiceProbeResult(
                "牛牛画画",
                "AI runtime",
                True,
                None,
                None,
                "正常（开启回退）",
                runtime_state="healthy",
                runtime_detail="正常（开启回退）",
                capability_id="image.generate",
                capability_group="media",
                runtime_type="image",
                failure_class=None,
                health_state="healthy",
                circuit_state="closed",
                consecutive_failures=0,
                recent_failure_class=None,
                queue_load_hint="low",
            )
        ]

    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    monkeypatch.setattr(
        "pallas.product.service_gateways.collect.probe_all_connectivity_from_draft",
        fake_probe_all_connectivity_from_draft,
    )

    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    client = TestClient(app)

    response = client.post(
        "/pallas/api/common-config/service_gateways/connectivity-check",
        json={"values": {}},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["results"][0]["runtime_state"] == "healthy"
    assert payload["data"]["results"][0]["runtime_detail"] == "正常（开启回退）"
    assert payload["data"]["results"][0]["capability_id"] == "image.generate"
    assert payload["data"]["results"][0]["capability_group"] == "media"
    assert payload["data"]["results"][0]["runtime_type"] == "image"
    assert payload["data"]["results"][0]["failure_class"] is None
    assert payload["data"]["results"][0]["health_state"] == "healthy"
    assert payload["data"]["results"][0]["circuit_state"] == "closed"
    assert payload["data"]["results"][0]["consecutive_failures"] == 0
    assert payload["data"]["results"][0]["recent_failure_class"] is None
    assert payload["data"]["results"][0]["queue_load_hint"] == "low"
