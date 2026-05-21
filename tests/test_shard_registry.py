import pytest

from src.common.shard.registry.config import get_shard_registry_settings
from src.common.shard.registry.store import (
    ShardRegistry,
    assign_bot_to_shard,
    clear_shard_registry_cache,
    get_shard_registry,
    resolve_onebot_ws_url_for_bot,
    save_shard_registry,
)


@pytest.fixture(autouse=True)
def _clear_shard_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    monkeypatch.setenv("PALLAS_SHARD_BOTS_PER", "5")
    monkeypatch.setenv("PALLAS_SHARD_WORKER_BASE_PORT", "8090")
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()
    yield
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()


def test_assign_respects_bots_per_shard(monkeypatch):
    reg = ShardRegistry(bots_per_shard=2, worker_base_port=8090, ws_host="127.0.0.1")
    save_shard_registry(reg)
    clear_shard_registry_cache()
    assert assign_bot_to_shard("111") == 0
    assert assign_bot_to_shard("222") == 0
    assert assign_bot_to_shard("333") == 1
    url, _, _ = resolve_onebot_ws_url_for_bot("333")
    assert url == "ws://127.0.0.1:8091/onebot/v11/ws"


def test_existing_bot_keeps_shard():
    reg = get_shard_registry()
    reg.assignments["999"] = 3
    save_shard_registry(reg)
    clear_shard_registry_cache()
    assert assign_bot_to_shard("999") == 3
