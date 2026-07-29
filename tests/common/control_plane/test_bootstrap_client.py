from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.product.control_plane import bootstrap_client as bc


@pytest.fixture
def community_state_file(tmp_path, monkeypatch):
    path = tmp_path / "community_stats.json"
    monkeypatch.setattr(
        "pallas.product.community_stats.store.community_stats_state_path",
        lambda: path,
    )
    monkeypatch.setattr(
        "pallas.product.control_plane.store._read_state_raw",
        lambda: json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {},
    )

    def write_state(data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr("pallas.product.control_plane.store._write_state", write_state)
    return path


def test_bootstrap_url_from_heartbeat():
    assert bc.bootstrap_url_from_heartbeat("https://stats.pallasbot.top/v1/heartbeat") == (
        "https://stats.pallasbot.top/v1/bootstrap"
    )


@pytest.mark.asyncio
async def test_refresh_bootstrap_saves_coord(community_state_file, monkeypatch, tmp_path):
    dep = str(uuid.uuid4())
    monkeypatch.setenv("PALLAS_CONTROL_PLANE_ENABLED", "true")
    monkeypatch.setenv("PALLAS_INSTANCE_SECRET", "sec")
    monkeypatch.setenv("PALLAS_CONTROL_PLANE_BOOTSTRAP_URL", "https://stats.example/v1/bootstrap")
    bc.clear_bootstrap_runtime_caches()
    from pallas.product.control_plane.config import clear_control_plane_config_cache

    clear_control_plane_config_cache()

    monkeypatch.setattr(bc, "load_or_create_deployment_id", lambda: dep)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "federate_id": "pool-a",
        "coord": {
            "redis_url": "redis://coord:6379/2",
            "redis_prefix": "pallas:fed:pool-a",
            "claim_ttl_sec": 7200,
        },
        "expires_at": 9999999999,
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(bc.httpx, "AsyncClient", lambda **kw: mock_client)
    monkeypatch.setattr(bc, "should_run_bootstrap_refresh", lambda: True)

    ok = await bc.refresh_control_plane_bootstrap(force=True)
    assert ok is True
    data = json.loads(community_state_file.read_text(encoding="utf-8"))
    assert data["federate_id"] == "pool-a"
    assert data["control_plane_bootstrap"]["coord"]["redis_url"] == "redis://coord:6379/2"

    from pallas.product.control_plane.store import load_bootstrap_coord_redis_url

    assert load_bootstrap_coord_redis_url() == "redis://coord:6379/2"


@pytest.mark.asyncio
async def test_refresh_bootstrap_saves_corpus_community_snapshot(community_state_file, monkeypatch):
    dep = str(uuid.uuid4())
    monkeypatch.setenv("PALLAS_CONTROL_PLANE_ENABLED", "true")
    monkeypatch.setenv("PALLAS_INSTANCE_SECRET", "sec")
    monkeypatch.setenv("PALLAS_CONTROL_PLANE_BOOTSTRAP_URL", "https://stats.example/v1/bootstrap")
    bc.clear_bootstrap_runtime_caches()
    from pallas.product.control_plane.config import clear_control_plane_config_cache

    clear_control_plane_config_cache()

    monkeypatch.setattr(bc, "load_or_create_deployment_id", lambda: dep)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "federate_id": "pool-a",
        "coord": {
            "redis_url": "redis://coord:6379/2",
        },
        "corpus_community": {
            "api_base": "https://stats.example/v1/corpus",
            "readable": True,
            "writable": False,
        },
        "expires_at": 9999999999,
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(bc.httpx, "AsyncClient", lambda **kw: mock_client)
    monkeypatch.setattr(bc, "should_run_bootstrap_refresh", lambda: True)

    ok = await bc.refresh_control_plane_bootstrap(force=True)
    assert ok is True
    data = json.loads(community_state_file.read_text(encoding="utf-8"))
    assert data["control_plane_bootstrap"]["corpus_community"]["api_base"] == "https://stats.example/v1/corpus"


@pytest.mark.asyncio
async def test_autofill_instance_secret_from_onboarding(monkeypatch, tmp_path):
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("PALLAS_CONTROL_PLANE_ENABLED", "true")
    monkeypatch.delenv("PALLAS_INSTANCE_SECRET", raising=False)
    for mod in (
        "pallas.core.foundation.config.repo_settings",
        "pallas.product.control_plane.webui_config",
    ):
        monkeypatch.setattr(f"{mod}.repo_webui_settings_path", lambda: webui)
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache
    from pallas.product.control_plane.config import clear_control_plane_config_cache

    clear_merged_repo_settings_cache()
    clear_control_plane_config_cache()
    bc.clear_bootstrap_runtime_caches()

    async def fake_onboarding():
        return {"instance_secret": "auto-secret-from-center"}

    monkeypatch.setattr(
        "pallas.product.community_stats.federation_onboarding.fetch_federation_onboarding",
        fake_onboarding,
    )
    ok = await bc.maybe_autofill_instance_secret_from_onboarding()
    assert ok is True
    env = json.loads(webui.read_text(encoding="utf-8"))["env"]
    assert env["PALLAS_INSTANCE_SECRET"] == "auto-secret-from-center"
    clear_control_plane_config_cache()
    from pallas.product.control_plane.config import get_control_plane_config

    assert get_control_plane_config().instance_secret == "auto-secret-from-center"


def test_should_run_bootstrap_without_secret_when_control_plane_enabled(monkeypatch):
    monkeypatch.setenv("PALLAS_CONTROL_PLANE_ENABLED", "true")
    monkeypatch.delenv("PALLAS_INSTANCE_SECRET", raising=False)
    monkeypatch.setenv("PALLAS_CONTROL_PLANE_BOOTSTRAP_URL", "https://stats.example/v1/bootstrap")
    from pallas.product.control_plane.config import clear_control_plane_config_cache, should_run_bootstrap_refresh

    clear_control_plane_config_cache()
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.roles.is_sharded_worker",
        lambda: False,
    )
    assert should_run_bootstrap_refresh() is True
