import pytest

from pallas.core.platform.shard.registry.config import get_shard_registry_settings
from pallas.core.platform.shard.registry.store import (
    ShardRegistry,
    assign_bot_to_shard,
    clear_shard_registry_cache,
    get_shard_registry,
    rebalance_production_assignments,
    resolve_onebot_ws_url_for_bot,
    save_shard_registry,
)


@pytest.fixture(autouse=True)
def _clear_shard_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    monkeypatch.setenv("PALLAS_SHARD_BOTS_PER", "5")
    monkeypatch.setenv("PALLAS_SHARD_WORKER_BASE_PORT", "8090")
    monkeypatch.setenv("PALLAS_SHARD_AUTO_SCALE_WORKERS", "false")
    reg_dir = tmp_path / "pallas_shard"
    reg_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.store._registry_path",
        lambda: reg_dir / "registry.json",
    )
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()
    yield
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()


def test_assign_respects_bots_per_shard(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_BOTS_PER", "2")
    get_shard_registry_settings.cache_clear()
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


def test_rebalance_production_assignments_compacts_shards(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_BOTS_PER", "3")
    get_shard_registry_settings.cache_clear()
    reg = ShardRegistry(bots_per_shard=3, worker_base_port=8090, ws_host="127.0.0.1")
    reg.assignments = {"1": 0, "2": 0, "3": 1, "4": 1, "5": 8, "6": 8}
    result = rebalance_production_assignments(registry=reg, save=False)
    assert result["worker_shards"] == 2
    assert reg.assignments["1"] == 0
    assert reg.assignments["4"] == 1
    assert reg.assignments["6"] == 1
    assert result["moved"] >= 1


def test_rebalance_production_assignments_activity_strategy_spreads_hot_bots(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_BOTS_PER", "3")
    get_shard_registry_settings.cache_clear()
    reg = ShardRegistry(bots_per_shard=3, worker_base_port=8090, ws_host="127.0.0.1")
    reg.assignments = {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1, "6": 1}
    result = rebalance_production_assignments(
        registry=reg,
        save=False,
        strategy="activity",
        activity_scores={
            "1": 100.0,
            "2": 90.0,
            "3": 80.0,
            "4": 1.0,
            "5": 1.0,
            "6": 1.0,
        },
    )
    assert result["worker_shards"] == 2
    assert len({reg.assignments["1"], reg.assignments["2"], reg.assignments["3"]}) == 2
    assert result["moved"] >= 1
