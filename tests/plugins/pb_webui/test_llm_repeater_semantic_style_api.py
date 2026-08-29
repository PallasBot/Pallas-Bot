from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config


def _build_app(monkeypatch) -> FastAPI:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return app


async def request(monkeypatch, method: str, url: str, **kwargs):
    app = _build_app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


@pytest.mark.asyncio
async def test_repeater_semantic_style_status_api(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    monkeypatch.setattr(
        semantic_style,
        "semantic_style_status",
        lambda: {"enabled": True, "example_count": 3, "profile_count": 2},
        raising=False,
    )

    response = await request(monkeypatch, "GET", "/pallas/api/llm/repeater-semantic-style")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "data": {"enabled": True, "example_count": 3, "profile_count": 2},
    }


@pytest.mark.asyncio
async def test_repeater_semantic_style_quality_response_is_typed_and_has_no_quota(monkeypatch) -> None:
    from packages.pb_webui import llm_product_api
    from packages.pb_webui.llm_product_api import register_llm_product_router
    from pallas.product.llm import repeater_semantic_style as semantic_style

    monkeypatch.setattr(
        semantic_style,
        "semantic_style_quality",
        lambda **scope: {
            "enabled": True,
            "direct_enabled": True,
            "example_count": 3,
            "profile_count": 1,
            "backfill_cursor": {},
            "label_version": 2,
            "positive_bot_style_count": 2,
            "outcome_counts": {"engaged": 2},
            "reuse_counts": {"direct": 1},
            "realtime_admission": {"quota": 100},
        },
    )

    monkeypatch.setattr(llm_product_api, "check_pallas_write_token", lambda *args, **kwargs: None)
    monkeypatch.setattr(semantic_style, "refresh_semantic_style_cache", lambda *, force=False: None)
    monkeypatch.setattr(semantic_style, "cached_semantic_style_profile", lambda *args: None)
    app = FastAPI()
    register_llm_product_router(app.router, x="/pallas/api", plugin_config=Config())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/pallas/api/llm/repeater-semantic-style/manage",
            json={"action": "quality", "bot_id": 100, "group_id": 42},
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "status": {
            "enabled": True,
            "direct_enabled": True,
            "example_count": 3,
            "profile_count": 1,
            "backfill_cursor": {},
        },
        "label_version": 2,
        "positive_bot_style_count": 2,
    }


@pytest.mark.asyncio
async def test_repeater_semantic_style_api_forwards_bot_group_scope(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    calls: list[tuple[str, int | None, int | None]] = []
    monkeypatch.setattr(
        semantic_style,
        "semantic_style_status",
        lambda *, bot_id=None, group_id=None: calls.append(("status", bot_id, group_id)) or {"enabled": True},
    )
    monkeypatch.setattr(
        semantic_style,
        "set_semantic_style_direct_enabled",
        lambda enabled, *, bot_id=None, group_id=None: (
            calls.append(("direct_enabled", bot_id, group_id)) or {"enabled": True, "direct_enabled": enabled}
        ),
    )
    app = _build_app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/pallas/api/llm/repeater-semantic-style?bot_id=100&group_id=42")
        updated = await client.post(
            "/pallas/api/llm/repeater-semantic-style/manage",
            json={"action": "direct_enabled", "bot_id": 100, "group_id": 42, "direct_enabled": False},
        )
        incomplete = await client.get("/pallas/api/llm/repeater-semantic-style?bot_id=100")

    assert status.status_code == 200, status.text
    assert updated.status_code == 200, updated.text
    assert incomplete.status_code == 422
    assert calls == [("status", 100, 42), ("direct_enabled", 100, 42)]


@pytest.mark.asyncio
async def test_repeater_semantic_style_manage_api_dispatches_actions(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        semantic_style,
        "set_semantic_style_direct_enabled",
        lambda enabled: calls.append(("direct_enabled", enabled)) or {"enabled": True, "direct_enabled": enabled},
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
    app = _build_app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for body in (
            {"action": "direct_enabled", "direct_enabled": False},
            {"action": "clear"},
            {"action": "rebuild"},
            {"action": "quality"},
            {"action": "recover"},
            {"action": "disable"},
        ):
            response = await client.post("/pallas/api/llm/repeater-semantic-style/manage", json=body)
            assert response.status_code == 200, response.text
            assert response.json()["ok"] is True

    assert calls == [
        ("direct_enabled", False),
        ("clear", None),
        ("rebuild", None),
        ("quality", None),
        ("recover", None),
        ("disable", False),
    ]


@pytest.mark.asyncio
async def test_repeater_semantic_style_direct_enabled_action_requires_boolean(monkeypatch) -> None:
    response = await request(
        monkeypatch,
        "POST",
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "direct_enabled"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "direct_enabled 必须为布尔值"


@pytest.mark.asyncio
async def test_repeater_semantic_style_direct_enabled_action_forwards_flag(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    calls: list[tuple[bool]] = []
    monkeypatch.setattr(
        semantic_style,
        "set_semantic_style_direct_enabled",
        lambda enabled: calls.append((enabled,)) or {"enabled": True, "direct_enabled": enabled},
        raising=False,
    )

    response = await request(
        monkeypatch,
        "POST",
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "direct_enabled", "direct_enabled": False},
    )

    assert response.status_code == 200, response.text
    assert calls == [(False,)]
    assert response.json()["data"]["direct_enabled"] is False


@pytest.mark.asyncio
async def test_repeater_semantic_style_manage_rejects_unknown_action(monkeypatch) -> None:
    response = await request(
        monkeypatch,
        "POST",
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "action"]


@pytest.mark.asyncio
async def test_repeater_semantic_style_manage_checks_write_token(monkeypatch) -> None:
    from packages.pb_webui import llm_product_api
    from pallas.product.llm import repeater_semantic_style as semantic_style

    checked: list[bool] = []
    monkeypatch.setattr(
        llm_product_api,
        "check_pallas_write_token",
        lambda *args, **kwargs: checked.append(True),
    )
    monkeypatch.setattr(semantic_style, "semantic_style_status", lambda: {"enabled": True})

    response = await request(
        monkeypatch,
        "POST",
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "status"},
    )

    assert response.status_code == 200, response.text
    assert checked == [True]


@pytest.mark.asyncio
async def test_repeater_semantic_style_set_governance_dispatches_both_flags(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        semantic_style,
        "set_semantic_style_governance",
        lambda **kwargs: (
            calls.append(kwargs)
            or {
                "enabled": True,
                "collection_enabled": kwargs.get("collection_enabled"),
                "injection_enabled": kwargs.get("injection_enabled"),
            }
        ),
        raising=False,
    )

    response = await request(
        monkeypatch,
        "POST",
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={
            "action": "set_governance",
            "bot_id": 100,
            "group_id": 42,
            "collection_enabled": False,
            "injection_enabled": True,
        },
    )

    assert response.status_code == 200, response.text
    assert calls == [{"bot_id": 100, "group_id": 42, "collection_enabled": False, "injection_enabled": True}]
    assert response.json()["data"]["collection_enabled"] is False
    assert response.json()["data"]["injection_enabled"] is True


@pytest.mark.asyncio
async def test_repeater_semantic_style_set_governance_requires_both_flags(monkeypatch) -> None:
    response = await request(
        monkeypatch,
        "POST",
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "set_governance", "bot_id": 100, "group_id": 42, "collection_enabled": False},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_repeater_semantic_style_clear_forwards_continue_learning(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        semantic_style,
        "clear_semantic_style_data",
        lambda **kwargs: (
            calls.append(kwargs)
            or {"collection_enabled": kwargs.get("continue_learning", True), "injection_enabled": True}
        ),
        raising=False,
    )

    response = await request(
        monkeypatch,
        "POST",
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "clear", "bot_id": 100, "group_id": 42, "continue_learning": False},
    )

    assert response.status_code == 200, response.text
    assert calls == [{"bot_id": 100, "group_id": 42, "continue_learning": False}]
    assert response.json()["data"]["collection_enabled"] is False


@pytest.mark.asyncio
async def test_repeater_semantic_style_enable_action_sets_both_true(monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as semantic_style

    calls: list[tuple[bool, int | None, int | None]] = []
    monkeypatch.setattr(
        semantic_style,
        "set_semantic_style_enabled",
        lambda enabled, *, bot_id=None, group_id=None: (
            calls.append((enabled, bot_id, group_id))
            or {"enabled": True, "collection_enabled": enabled, "injection_enabled": enabled}
        ),
        raising=False,
    )

    response = await request(
        monkeypatch,
        "POST",
        "/pallas/api/llm/repeater-semantic-style/manage",
        json={"action": "enable", "bot_id": 100, "group_id": 42},
    )

    assert response.status_code == 200, response.text
    assert calls == [(True, 100, 42)]
    assert response.json()["data"]["collection_enabled"] is True
    assert response.json()["data"]["injection_enabled"] is True
