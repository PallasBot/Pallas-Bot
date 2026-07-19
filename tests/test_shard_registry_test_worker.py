import pytest

from pallas.core.platform.shard.registry.config import get_shard_registry_settings
from pallas.core.platform.shard.registry.store import (
    ShardRecord,
    ShardRegistry,
    TestShardConfig,
    _ensure_shard_rows,
    apply_registry_settings_from_env,
    assign_bot_to_shard,
    assign_bot_to_test_shard,
    clear_shard_registry_cache,
    get_shard_registry,
    get_test_shard_id,
    init_test_shard,
    list_test_shard_bots,
    remove_bot_from_test_shard,
    resolve_test_port,
    save_shard_registry,
)


@pytest.fixture(autouse=True)
def _clear_shard_caches(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    monkeypatch.setenv("PALLAS_SHARD_BOTS_PER", "5")
    monkeypatch.setenv("PALLAS_SHARD_WORKER_BASE_PORT", "8090")
    monkeypatch.setenv("PALLAS_SHARD_TEST_ID", "99")
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()
    yield
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()


def test_ensure_shard_rows_prunes_empty_shards(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_BOTS_PER", "5")
    reg = ShardRegistry(
        bots_per_shard=5,
        worker_base_port=8090,
        assignments={"111": 0},
        shards=[ShardRecord(id=i, port=8090 + i, bot_ids=[]) for i in range(100)],
    )
    reg.test = TestShardConfig(enabled=True, shard_id=99, port=8199)
    apply_registry_settings_from_env(reg)
    _ensure_shard_rows(reg)
    normal_ids = [s.id for s in reg.shards if s.role != "test"]
    assert normal_ids == [0]
    assert any(s.id == 99 and s.role == "test" for s in reg.shards)


def test_resolve_test_port_picks_above_normal_workers():
    reg = ShardRegistry(
        bots_per_shard=5,
        worker_base_port=8090,
        shards=[
            ShardRecord(id=0, port=8090, bot_ids=[]),
            ShardRecord(id=1, port=8095, bot_ids=[]),
        ],
    )
    reg.test = TestShardConfig(enabled=True, shard_id=99, port=0)
    assert resolve_test_port(reg) == 8096


def test_auto_assign_skips_test_shard(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_BOTS_PER", "2")
    get_shard_registry_settings.cache_clear()
    reg = ShardRegistry(bots_per_shard=2, worker_base_port=8090, ws_host="127.0.0.1")
    init_test_shard(registry=reg, port=8199, shard_id=99)
    save_shard_registry(reg)
    clear_shard_registry_cache()
    assert assign_bot_to_shard("111") == 0
    assert assign_bot_to_shard("222") == 0
    assert assign_bot_to_shard("333") == 1
    assert assign_bot_to_shard("444") != 99
    assert get_test_shard_id() == 99
    assert list_test_shard_bots(registry=reg) == []


def test_manual_assign_to_test_shard():
    reg = ShardRegistry(bots_per_shard=2, worker_base_port=8090, ws_host="127.0.0.1")
    init_test_shard(registry=reg, port=8199, shard_id=99)
    clear_shard_registry_cache()
    sid = assign_bot_to_test_shard("555555")
    assert sid == 99
    reg = get_shard_registry()
    assert reg.assignments["555555"] == 99
    assert assign_bot_to_shard("666666") != 99
    remove_bot_from_test_shard("555555")
    clear_shard_registry_cache()
    reg = get_shard_registry()
    assert "555555" not in reg.assignments
