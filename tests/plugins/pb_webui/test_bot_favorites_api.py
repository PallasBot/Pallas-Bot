from __future__ import annotations

from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from packages.pb_webui import bot_favorites_api as mod


def configure_storage(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "pallas.core.storage.deploy_store.deploy_storage_path",
        lambda _plugin_name: tmp_path / "plugin_storage.json",
    )


def test_bot_favorites_storage_distinguishes_uninitialized_and_empty(monkeypatch, tmp_path) -> None:
    configure_storage(monkeypatch, tmp_path)

    assert mod.load_bot_favorites() == {"initialized": False, "accounts": []}

    assert mod.save_bot_favorites([]) == {"initialized": True, "accounts": []}
    assert mod.load_bot_favorites() == {"initialized": True, "accounts": []}


def test_bot_favorites_storage_normalizes_accounts(monkeypatch, tmp_path) -> None:
    configure_storage(monkeypatch, tmp_path)

    saved = mod.save_bot_favorites([2927116873, 10001, 2927116873])

    assert saved == {"initialized": True, "accounts": [10001, 2927116873]}
    assert mod.load_bot_favorites() == saved


def build_app(check_write_token) -> FastAPI:
    app = FastAPI()
    router = APIRouter()
    mod.register_bot_favorites_router(
        router,
        x="/pallas/api",
        check_write_token=check_write_token,
    )
    app.include_router(router)
    return app


async def test_bot_favorites_routes_read_and_replace(monkeypatch, tmp_path) -> None:
    configure_storage(monkeypatch, tmp_path)
    auth_calls: list[tuple[str | None, str | None]] = []
    app = build_app(
        lambda *, x_pallas_token=None, token=None: auth_calls.append((x_pallas_token, token)),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        initial = await client.get("/pallas/api/preferences/bot-favorites")
        updated = await client.put(
            "/pallas/api/preferences/bot-favorites",
            headers={"X-Pallas-Token": "header-token"},
            json={"accounts": [2927116873, 10001]},
        )

    assert initial.json() == {"ok": True, "data": {"initialized": False, "accounts": []}}
    assert updated.json() == {
        "ok": True,
        "data": {"initialized": True, "accounts": [10001, 2927116873]},
    }
    assert auth_calls == [("header-token", None)]


async def test_bot_favorites_route_rejects_non_positive_accounts(monkeypatch, tmp_path) -> None:
    configure_storage(monkeypatch, tmp_path)
    app = build_app(lambda **_: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/pallas/api/preferences/bot-favorites",
            json={"accounts": [0, -1]},
        )

    assert response.status_code == 422
    assert mod.load_bot_favorites() == {"initialized": False, "accounts": []}
