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
