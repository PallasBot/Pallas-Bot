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


def test_plugin_store_readme_returns_cached_markdown(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.get_cached_readme_markdown",
        lambda kind, target_id: "# Draw\n" if kind == "official" and target_id == "pallas-plugin-draw" else None,
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/store/readme", params={"kind": "official", "id": "pallas-plugin-draw"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["markdown"] == "# Draw\n"


def test_plugin_store_readme_accepts_official_plugin_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.resolve_readme_request_id",
        lambda kind, target_id: "pallas-plugin-ai-media" if kind == "official" and target_id == "sing" else target_id,
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.get_cached_readme_markdown",
        lambda kind, target_id: (
            "# AI Media\n" if kind == "official" and target_id == "pallas-plugin-ai-media" else None
        ),
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/store/readme", params={"kind": "official", "id": "sing"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["id"] == "pallas-plugin-ai-media"
    assert payload["data"]["markdown"] == "# AI Media\n"


def test_plugin_store_readme_fetches_on_cache_miss(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.resolve_readme_request_id",
        lambda kind, target_id: target_id,
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.get_cached_readme_markdown",
        lambda kind, target_id: None,
    )

    async def fake_fetch(kind: str, target_id: str, **kwargs) -> str | None:
        if kind == "official" and target_id == "pallas-plugin-draw":
            return "# Draw fetched\n"
        return None

    monkeypatch.setattr("pallas.console.webui.plugin_store_assets.fetch_and_cache_readme_markdown", fake_fetch)

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/store/readme", params={"kind": "official", "id": "pallas-plugin-draw"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["markdown"] == "# Draw fetched\n"


def test_plugin_store_changelog_returns_cached_markdown(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.resolve_readme_request_id",
        lambda kind, target_id: target_id,
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.get_cached_changelog_markdown",
        lambda kind, target_id: "# 更新日志\n" if kind == "community" and target_id == "interact" else None,
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/store/changelog", params={"kind": "community", "id": "interact"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["markdown"] == "# 更新日志\n"
    assert payload["data"]["source"] == "changelog"


def test_plugin_store_changelog_falls_back_to_git(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.resolve_readme_request_id",
        lambda kind, target_id: target_id,
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.get_cached_changelog_markdown",
        lambda kind, target_id: None,
    )

    async def fake_fetch(kind: str, target_id: str, **kwargs) -> str | None:
        return None

    async def fake_git(plugin_id: str) -> str | None:
        return "# 更新日志（自动生成）\n" if plugin_id == "interact" else None

    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.fetch_and_cache_changelog_markdown",
        fake_fetch,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_changelog.generate_community_changelog_from_git",
        fake_git,
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/store/changelog", params={"kind": "community", "id": "interact"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["source"] == "git"
    assert payload["data"]["markdown"].startswith("# 更新日志（自动生成）")


def test_plugin_store_changelog_404_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.resolve_readme_request_id",
        lambda kind, target_id: target_id,
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.get_cached_changelog_markdown",
        lambda kind, target_id: None,
    )

    async def fake_fetch(kind: str, target_id: str, **kwargs) -> str | None:
        return None

    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.fetch_and_cache_changelog_markdown",
        fake_fetch,
    )

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/plugins/store/changelog",
        params={"kind": "official", "id": "pallas-plugin-draw"},
    )

    assert response.status_code == 404, response.text


def test_plugin_store_assets_refresh_returns_counts(monkeypatch) -> None:
    async def fake_refresh() -> dict:
        return {
            "checked_at": 123.0,
            "official": {"pallas-plugin-draw": {}},
            "community": {"draw": {}, "duel": {}},
        }

    monkeypatch.setattr("pallas.console.webui.plugin_store_assets.refresh_store_asset_snapshot", fake_refresh)
    monkeypatch.setattr(mod, "drop_read_cache", lambda *a, **k: None)

    client = _build_client(monkeypatch)
    response = client.post("/pallas/api/plugins/store-assets/refresh")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["checked_at"] == 123.0
    assert payload["data"]["official_count"] == 1
    assert payload["data"]["community_count"] == 2


def test_community_store_refresh_also_refreshes_store_assets(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_build_store() -> dict:
        calls.append("build-community-store")
        return {"plugins": [], "meta": {}}

    async def fake_refresh_assets() -> dict:
        calls.append("refresh-store-assets")
        return {"checked_at": 456.0, "official": {}, "community": {}}

    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.build_community_plugin_store",
        fake_build_store,
    )
    monkeypatch.setattr("pallas.console.webui.plugin_store_assets.refresh_store_asset_snapshot", fake_refresh_assets)
    monkeypatch.setattr(mod, "drop_read_cache", lambda *a, **k: None)

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/community-store", params={"refresh": "true"})

    assert response.status_code == 200, response.text
    assert calls == ["refresh-store-assets", "build-community-store"]


def test_store_refresh_endpoint_refreshes_assets_and_updates(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_refresh_assets() -> dict:
        calls.append("assets")
        return {"checked_at": 111.0, "official": {"a": {}}, "community": {"b": {}}}

    async def fake_refresh_updates() -> dict:
        calls.append("updates")
        return {"checked_at": 222.0, "official": {"c": {}}, "community": {"d": {}, "e": {}}}

    monkeypatch.setattr("pallas.console.webui.plugin_store_assets.refresh_store_asset_snapshot", fake_refresh_assets)
    monkeypatch.setattr(
        "pallas.console.webui.plugin_update_snapshot.refresh_plugin_update_snapshot",
        fake_refresh_updates,
    )
    monkeypatch.setattr(mod, "drop_read_cache", lambda *a, **k: None)

    client = _build_client(monkeypatch)
    response = client.post("/pallas/api/plugins/store/refresh")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["store_assets"]["checked_at"] == 111.0
    assert payload["data"]["update_snapshot"]["checked_at"] == 222.0
    assert calls == ["assets", "updates"]
