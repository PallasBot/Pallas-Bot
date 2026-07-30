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
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_embedding_status_get(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_provider.build_embedding_status",
        lambda **kwargs: {
            "embedding_provider": "stub",
            "embedding_kind": "stub",
            "embedding_model": "stub",
            "resolved_model": "stub",
            "semantic_available": False,
            "embedding_fallback": False,
            "embedding_error": None,
            "available_providers": ["stub", "openai", "local"],
            "local_dependency_ready": False,
            "local_default_model": "BAAI/bge-small-zh-v1.5",
            "trigger_cache_count": 0,
            "trigger_cache_model": None,
            "probe_ok": None,
            "probe_dims": None,
            "probe_ms": None,
        },
    )
    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/common-config/llm/embedding-status")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["embedding_provider"] == "stub"
    assert "local" in body["data"]["available_providers"]


def test_embedding_status_probe(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_status(**kwargs):
        calls.append(dict(kwargs))
        return {
            "embedding_provider": "openai",
            "embedding_kind": "remote",
            "embedding_model": "text-embedding-3-small",
            "resolved_model": "text-embedding-3-small",
            "semantic_available": True,
            "embedding_fallback": False,
            "embedding_error": None,
            "available_providers": ["stub", "openai", "local"],
            "local_dependency_ready": False,
            "local_default_model": "BAAI/bge-small-zh-v1.5",
            "trigger_cache_count": 3,
            "trigger_cache_model": "text-embedding-3-small",
            "probe_ok": True,
            "probe_dims": 2,
            "probe_ms": 12.5,
        }

    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_provider.build_embedding_status",
        fake_status,
    )
    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/common-config/llm/embedding-status/probe",
        json={"text": "你好"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["probe_ok"] is True
    assert calls
    assert calls[0].get("probe") is True
