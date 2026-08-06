from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_repeater_semantic_style_status_api(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    monkeypatch.setattr(
        semantic_style,
        "semantic_style_status",
        lambda: {"enabled": True, "example_count": 3, "profile_count": 2},
        raising=False,
    )

    response = _build_client(monkeypatch).get("/pallas/api/llm/repeater-semantic-style")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "data": {"enabled": True, "example_count": 3, "profile_count": 2},
    }


def test_repeater_semantic_style_api_forwards_bot_group_scope(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    calls: list[tuple[str, int | None, int | None]] = []
    monkeypatch.setattr(
        semantic_style,
        "semantic_style_status",
        lambda *, bot_id=None, group_id=None: calls.append(("status", bot_id, group_id)) or {"enabled": True},
    )
    monkeypatch.setattr(
        semantic_style,
        "update_semantic_style_overrides",
        lambda overrides, *, bot_id=None, group_id=None: (
            calls.append(("overrides", bot_id, group_id)) or {"overrides": overrides}
        ),
    )
    client = _build_client(monkeypatch)

    status = client.get("/pallas/api/llm/repeater-semantic-style?bot_id=100&group_id=42")
    updated = client.post(
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "overrides", "bot_id": 100, "group_id": 42, "overrides": {"direct": False}},
    )
    incomplete = client.get("/pallas/api/llm/repeater-semantic-style?bot_id=100")

    assert status.status_code == 200, status.text
    assert updated.status_code == 200, updated.text
    assert incomplete.status_code == 422
    assert calls == [("status", 100, 42), ("overrides", 100, 42)]


def test_repeater_semantic_style_manage_api_dispatches_actions(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        semantic_style,
        "update_semantic_style_overrides",
        lambda overrides: calls.append(("overrides", overrides)) or {"enabled": True, "overrides": overrides},
        raising=False,
    )
    monkeypatch.setattr(
        semantic_style,
        "clear_semantic_style_data",
        lambda: calls.append(("clear", None)) or {"example_count": 0},
        raising=False,
    )
    monkeypatch.setattr(
        semantic_style,
        "rebuild_semantic_style_profiles",
        lambda: calls.append(("rebuild", None)) or {"profile_count": 2},
        raising=False,
    )
    monkeypatch.setattr(
        semantic_style,
        "semantic_style_quality",
        lambda: calls.append(("quality", None)) or {"labeled_count": 3},
        raising=False,
    )
    monkeypatch.setattr(
        semantic_style,
        "recover_semantic_style_data",
        lambda: calls.append(("recover", None)) or {"recovered": True},
        raising=False,
    )
    monkeypatch.setattr(
        semantic_style,
        "set_semantic_style_enabled",
        lambda enabled: calls.append(("disable", enabled)) or {"enabled": enabled},
        raising=False,
    )
    client = _build_client(monkeypatch)

    for body in (
        {"action": "overrides", "overrides": {"direct": False}},
        {"action": "clear"},
        {"action": "rebuild"},
        {"action": "quality"},
        {"action": "recover"},
        {"action": "disable"},
    ):
        response = client.post("/pallas/api/llm/repeater-semantic-style/manage", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True

    assert calls == [
        ("overrides", {"direct": False}),
        ("clear", None),
        ("rebuild", None),
        ("quality", None),
        ("recover", None),
        ("disable", False),
    ]


def test_repeater_semantic_style_manage_rejects_unknown_action(monkeypatch) -> None:
    response = _build_client(monkeypatch).post(
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "unknown"},
    )

    assert response.status_code == 400
    assert "action" in response.json()["detail"]


def test_repeater_semantic_style_manage_checks_write_token(monkeypatch) -> None:
    from packages.pb_webui import llm_product_api
    from pallas.product.llm import repeater_semantic_style as semantic_style

    checked: list[bool] = []
    monkeypatch.setattr(
        llm_product_api,
        "check_pallas_write_token",
        lambda *args, **kwargs: checked.append(True),
    )
    monkeypatch.setattr(semantic_style, "semantic_style_status", lambda: {"enabled": True})

    response = _build_client(monkeypatch).post(
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "status"},
    )

    assert response.status_code == 200, response.text
    assert checked == [True]
