from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config
from packages.pb_webui.console_read_cache import clear_extended_read_cache


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


@pytest.mark.asyncio
async def test_home_overview_payload_merges_slices(monkeypatch) -> None:
    clear_extended_read_cache()
    monkeypatch.setattr(
        "packages.pb_webui.api.read_current_health_payload",
        lambda: _async_return({"ok": True, "pallas_bot": "4.0.0"}),
    )
    monkeypatch.setattr(mod, "_system_dict", lambda: {"plugin_count": 3})
    monkeypatch.setattr(mod, "_list_bots_dict", lambda: [{"self_id": "1"}])
    monkeypatch.setattr(mod, "_instances_payload", lambda: _async_return({"nonebot_bots": []}))
    monkeypatch.setattr(mod, "_list_plugins_dict", lambda: [{"name": "pb_core"}])
    monkeypatch.setattr(mod, "_message_stats_overview", lambda **_kw: _async_return({"total": 9}))
    monkeypatch.setattr(
        mod,
        "_plugin_run_stats_overview",
        lambda **_kw: {"bots": [], "plugins": []},
    )
    monkeypatch.setattr(
        "pallas.product.community_stats.public_stats.fetch_community_public_stats",
        lambda: _async_return({"deployments_total": 2}),
    )

    out = await mod._home_overview_payload()

    assert out["health"]["pallas_bot"] == "4.0.0"
    assert out["system"]["plugin_count"] == 3
    assert out["bots"] == [{"self_id": "1"}]
    assert out["instances"] == {"nonebot_bots": []}
    assert out["plugins"] == [{"name": "pb_core"}]
    assert out["message_stats"] == {"total": 9}
    assert out["plugin_run_stats"] == {"bots": [], "plugins": []}
    assert out["community_stats"] == {"deployments_total": 2}


@pytest.mark.asyncio
async def test_home_overview_payload_tolerates_slice_failure(monkeypatch) -> None:
    clear_extended_read_cache()
    monkeypatch.setattr(
        "packages.pb_webui.api.read_current_health_payload",
        lambda: _async_return({"ok": True}),
    )
    monkeypatch.setattr(mod, "_system_dict", lambda: {"plugin_count": 1})
    monkeypatch.setattr(mod, "_list_bots_dict", list)
    monkeypatch.setattr(mod, "_instances_payload", lambda: _async_return({}))
    monkeypatch.setattr(mod, "_list_plugins_dict", lambda: _raise_runtime())
    monkeypatch.setattr(mod, "_message_stats_overview", lambda **_kw: _async_return({}))
    monkeypatch.setattr(mod, "_plugin_run_stats_overview", lambda **_kw: {})
    monkeypatch.setattr(
        "pallas.product.community_stats.public_stats.fetch_community_public_stats",
        lambda: _async_return({}),
    )

    out = await mod._home_overview_payload()

    assert out["system"]["plugin_count"] == 1
    assert out["plugins"] == []


def test_home_overview_route_returns_bundle(monkeypatch) -> None:
    sample = {
        "health": {"ok": True, "pallas_bot": "4.0.0"},
        "system": {"plugin_count": 1},
        "bots": [],
        "instances": {"nonebot_bots": []},
        "plugins": [],
        "message_stats": None,
        "plugin_run_stats": None,
        "community_stats": None,
    }
    monkeypatch.setattr(mod, "_home_overview_payload", lambda: _async_return(sample))
    clear_extended_read_cache()

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/home/overview")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["health"]["pallas_bot"] == "4.0.0"
    assert payload["data"]["system"]["plugin_count"] == 1
    assert payload["data"]["instances"] == {"nonebot_bots": []}


async def _async_return(value):
    return value


def _raise_runtime() -> None:
    raise RuntimeError("plugins failed")
