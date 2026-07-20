from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pallas.product.community_stats import config as cfg_mod
from pallas.product.community_stats import store as stats_store
from pallas.product.community_stats.endpoints import PRIMARY_HEARTBEAT

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def clear_config_cache():
    cfg_mod.clear_community_stats_config_cache()
    yield
    cfg_mod.clear_community_stats_config_cache()


@pytest.fixture
def community_state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "community_stats.json"
    monkeypatch.setattr(stats_store, "community_stats_state_path", lambda: path)
    stats_store.reset_community_stats_state_cache_for_tests()
    return path


def test_touch_last_heartbeat_ok_unix(community_state_file: Path) -> None:
    stats_store.touch_last_heartbeat_ok_unix(1_700_000_000)
    data = json.loads(community_state_file.read_text(encoding="utf-8"))
    assert data["last_heartbeat_ok_unix"] == 1_700_000_000


def _seed_community_state(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    stats_store.reset_community_stats_state_cache_for_tests()


@pytest.mark.asyncio
async def test_probe_community_connectivity_auto_mode_covers_primary_and_fallback(
    community_state_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.community_stats.connectivity_probe import probe_community_connectivity

    _seed_community_state(
        community_state_file,
        {
            "deployment_id": "123e4567-e89b-12d3-a456-426614174000",
            "heartbeat_endpoint": PRIMARY_HEARTBEAT,
            "last_heartbeat_ok_unix": 1_700_000_100,
            "last_primary_probe_unix": 1_700_000_050,
        },
    )
    monkeypatch.setattr(
        "pallas.product.community_stats.config.repo_env_raw_value",
        lambda _key: None,
    )
    cfg_mod.clear_community_stats_config_cache()

    async def fake_get(self, url, **kwargs):  # noqa: ANN001
        _ = kwargs
        if "stats.pallasbot.top" in str(url):
            return httpx.Response(200, json={"deployments_total": 1, "deployments_online": 1, "bots_online_sum": 1})
        raise httpx.ConnectError("boom", request=httpx.Request("GET", str(url)))

    with patch("httpx.AsyncClient.get", new=fake_get):
        payload = await probe_community_connectivity()

    assert [p["url"] for p in payload["probes"]] == [
        "https://stats.pallasbot.top/v1/stats",
        "https://pallas.togetsudo.com/v1/stats",
    ]
    assert payload["probes"][0]["ok"] is True
    assert payload["probes"][0]["http_status"] == 200
    assert payload["probes"][1]["ok"] is False
    assert payload["reporting"]["enabled"] is True
    assert payload["reporting"]["deployment_id"] == "123e4567-e89b-12d3-a456-426614174000"
    assert payload["reporting"]["last_heartbeat_ok_unix"] == 1_700_000_100
    assert payload["summary"]["any_ok"] is True
    assert "上报" in payload["summary"]["hint"]


@pytest.mark.asyncio
async def test_probe_community_connectivity_custom_endpoint_only(
    community_state_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.community_stats.connectivity_probe import probe_community_connectivity

    _ = community_state_file
    monkeypatch.setattr(
        "pallas.product.community_stats.config.repo_env_raw_value",
        lambda key: "https://stats.example/v1/heartbeat" if key == "PALLAS_COMMUNITY_STATS_ENDPOINT" else None,
    )
    cfg_mod.clear_community_stats_config_cache()

    async def fake_get(self, url, **kwargs):  # noqa: ANN001
        _ = self, kwargs, url
        return httpx.Response(200, json={"deployments_total": 0, "deployments_online": 0, "bots_online_sum": 0})

    with patch("httpx.AsyncClient.get", new=fake_get):
        payload = await probe_community_connectivity()

    assert len(payload["probes"]) == 1
    assert payload["probes"][0]["url"] == "https://stats.example/v1/stats"
    assert payload["probes"][0]["ok"] is True


@pytest.mark.asyncio
async def test_heartbeat_success_records_last_ok_unix(
    community_state_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.community_stats.reporter import send_community_stats_heartbeat

    _ = community_state_file
    monkeypatch.setattr(
        "pallas.product.community_stats.config.repo_env_raw_value",
        lambda _key: None,
    )
    cfg_mod.clear_community_stats_config_cache()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with (
        patch(
            "pallas.product.community_stats.reporter.load_or_create_deployment_id",
            return_value="123e4567-e89b-12d3-a456-426614174000",
        ),
        patch("pallas.product.community_stats.reporter.get_catalog_bot_ids", return_value=frozenset({1})),
        patch(
            "pallas.core.platform.shard.presence.count_connected_bots_for_reporting",
            return_value=1,
        ),
        patch("pallas.product.community_stats.reporter.httpx.AsyncClient", return_value=mock_client),
        patch("pallas.product.community_stats.reporter.is_sharded_worker", return_value=False),
    ):
        assert await send_community_stats_heartbeat() is True

    state = stats_store.load_community_stats_state()
    assert int(state.get("last_heartbeat_ok_unix") or 0) > 0


def test_connectivity_check_api_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from packages.pb_webui import extended_api as mod
    from packages.pb_webui.config import Config

    async def fake_probe():
        return {
            "probes": [
                {
                    "url": "https://stats.pallasbot.top/v1/stats",
                    "ok": True,
                    "latency_ms": 12,
                    "http_status": 200,
                    "error": None,
                }
            ],
            "reporting": {
                "enabled": True,
                "endpoint": PRIMARY_HEARTBEAT,
                "active_heartbeat_endpoint": PRIMARY_HEARTBEAT,
                "deployment_id": "123e4567-e89b-12d3-a456-426614174000",
                "last_heartbeat_ok_unix": 1,
                "last_primary_probe_unix": 2,
            },
            "summary": {"any_ok": True, "hint": "主站可达；上报已开启"},
        }

    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    monkeypatch.setattr(
        "pallas.product.community_stats.connectivity_probe.probe_community_connectivity",
        fake_probe,
    )

    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    client = TestClient(app)

    response = client.post("/pallas/api/community-stats/connectivity-check", json={})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["summary"]["any_ok"] is True
    assert payload["data"]["probes"][0]["ok"] is True
