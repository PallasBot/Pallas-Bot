from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config
from pallas.product.llm.behavior import BehaviorAction, BehaviorPattern, BehaviorScene


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_llm_behavior_patterns_get_filters_by_group_and_scene(monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "list_behavior_patterns",
        lambda: [
            BehaviorPattern(
                pattern_id="global-1",
                scene=BehaviorScene.PROVOCATION,
                action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            ),
            BehaviorPattern(
                pattern_id="group-1",
                scene=BehaviorScene.PROVOCATION,
                action=BehaviorAction.ACK_THEN_SHORT_REPLY,
                scope_group_id=20002,
                disabled=True,
            ),
            BehaviorPattern(
                pattern_id="other-group",
                scene=BehaviorScene.BANTER,
                action=BehaviorAction.FOLLOW_JOKE_ONCE,
                scope_group_id=30003,
            ),
        ],
    )

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/common-config/llm/behavior/patterns",
        params={"group_id": 20002, "scene": "provocation", "include_disabled": False},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["items"][0]["pattern_id"] == "global-1"


def test_llm_behavior_patterns_upsert_post(monkeypatch) -> None:
    def fake_upsert(pattern: BehaviorPattern) -> BehaviorPattern:
        assert pattern.pattern_id == "p1"
        assert pattern.scene == BehaviorScene.PROVOCATION
        assert pattern.action == BehaviorAction.LIGHT_TEASE_AND_CLOSE
        assert pattern.scope_group_id == 20002
        return pattern

    monkeypatch.setattr(mod, "upsert_behavior_pattern", fake_upsert)

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/common-config/llm/behavior/patterns/upsert",
        json={
            "pattern_id": "p1",
            "scene": "provocation",
            "action": "light_tease_and_close",
            "scope_group_id": 20002,
            "success_score": 2,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["pattern_id"] == "p1"
    assert payload["data"]["scope_group_id"] == 20002


def test_llm_behavior_patterns_delete_post(monkeypatch) -> None:
    monkeypatch.setattr(mod, "delete_behavior_pattern", lambda pattern_id: pattern_id == "p1")

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/common-config/llm/behavior/patterns/delete",
        json={"pattern_id": "p1"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["pattern_id"] == "p1"
