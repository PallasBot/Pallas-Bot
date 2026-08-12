from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config
from pallas.product.persona.expression_bank import ExpressionEntry


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def _entry(*, status: str = "shadow") -> ExpressionEntry:
    return ExpressionEntry(
        entry_id="expr-123-abc",
        group_id=123,
        occasion="调侃",
        saying="少来。",
        source="llm_success",
        channel="group",
        scene_tier="strong",
        status=status,
        affect_hint="playful",
        created_at=1718700001,
        updated_at=1718700002,
    )


def test_expression_bank_api_lists_group_entries_with_status(monkeypatch) -> None:
    def fake_list_group_expressions(*, group_id: int, status: str | None = None, limit: int = 50):
        assert group_id == 123
        assert status == "shadow"
        assert limit == 20
        return [_entry()]

    monkeypatch.setattr("packages.pb_webui.llm_product_api.list_group_expressions", fake_list_group_expressions)

    response = _build_client(monkeypatch).get(
        "/pallas/api/llm/expression-bank",
        params={"group_id": 123, "status": "shadow", "limit": 20},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "data": {"items": [_entry().model_dump(mode="json")], "limit": 20},
    }


def test_expression_bank_resolve_api_approves_entry(monkeypatch) -> None:
    def fake_resolve_expression(entry_id: str, *, action: str, reason: str = ""):
        assert entry_id == "expr-123-abc"
        assert action == "approve"
        assert reason == ""
        return _entry(status="active")

    monkeypatch.setattr("packages.pb_webui.llm_product_api.resolve_expression", fake_resolve_expression)

    response = _build_client(monkeypatch).post(
        "/pallas/api/llm/expression-bank/resolve",
        json={"entry_id": "expr-123-abc", "action": "approve"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "active"
