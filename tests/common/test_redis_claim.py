from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.platform.coord import redis_claim as rc
from src.platform.coord import redis_settings as rs
from src.platform.multi_bot import claim as claim_mod


@pytest.fixture(autouse=True)
def clear_redis_caches():
    rs.clear_coord_redis_settings_cache()
    rc.clear_coord_redis_client_cache()
    yield
    rs.clear_coord_redis_settings_cache()
    rc.clear_coord_redis_client_cache()


def test_claim_redis_key():
    assert rc.claim_redis_key("ingress_gate_shard", 1, 999).startswith("pallas:msg_claim:")


def test_try_claim_message_redis_sync(monkeypatch):
    client = MagicMock()
    client.set.return_value = True
    monkeypatch.setattr(rc, "get_coord_redis_client", lambda: client)
    assert rc.try_claim_message_redis_sync("p", 1, 2, 100) is True
    client.set.assert_called_once()
    assert client.set.call_args.kwargs.get("nx") is True


def test_try_claim_message_falls_back_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "try_claim_message_redis_sync", lambda *a, **k: None)
    monkeypatch.setattr(claim_mod, "plugin_data_dir", lambda plugin, create=True: tmp_path / plugin)
    assert claim_mod.try_claim_message_sync("p", 1, 2, 100) is True
    assert claim_mod.read_claim_owner_sync("p", 1, 2) == 100


def test_try_claim_message_sharding_does_not_fall_back_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "try_claim_message_redis_sync", lambda *a, **k: None)
    monkeypatch.setattr(claim_mod, "plugin_data_dir", lambda plugin, create=True: tmp_path / plugin)
    monkeypatch.setattr(
        "src.platform.shard.registry.config.is_sharding_active",
        lambda: True,
    )
    assert claim_mod.try_claim_message_sync("p", 1, 2, 100) is False
    assert claim_mod.read_claim_owner_sync("p", 1, 2) is None


def test_coord_redis_required_when_sharding(monkeypatch):
    monkeypatch.setattr(
        "src.platform.shard.registry.config.is_sharding_active",
        lambda: True,
    )
    monkeypatch.setattr(rs, "coord_redis_enabled", lambda: False)

    with pytest.raises(RuntimeError, match="Redis"):
        rs.ensure_coord_redis_ready_for_sharding()


def test_coord_redis_enabled_respects_false(monkeypatch):
    monkeypatch.setattr(
        rs,
        "_setting",
        lambda key: {
            "PALLAS_COORD_REDIS_ENABLED": "false",
            "REDIS_URL": "redis://127.0.0.1:6379/0",
        }.get(key),
    )
    rs.clear_coord_redis_settings_cache()
    assert rs.coord_redis_enabled() is False
