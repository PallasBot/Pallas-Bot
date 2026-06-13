from __future__ import annotations

import pytest

from src.plugins.help import global_disable, group_fleet_whitelist, plugin_manager


def test_save_and_load_group_fleet_whitelist(tmp_path, monkeypatch):
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    group_fleet_whitelist.invalidate_group_fleet_whitelist_cache()

    assert group_fleet_whitelist.load_group_fleet_whitelist() == []

    saved = group_fleet_whitelist.save_group_fleet_whitelist([
        {"group_id": 626266902, "plugins": ["ollama", "ollama"]},
        {"group_id": 733291779, "plugins": ["chat"]},
    ])
    assert saved == [
        {"group_id": 626266902, "plugins": ["ollama"]},
        {"group_id": 733291779, "plugins": ["chat"]},
    ]
    assert group_fleet_whitelist.load_group_fleet_whitelist() == saved


def test_add_group_fleet_whitelist_plugin_merges_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    group_fleet_whitelist.invalidate_group_fleet_whitelist_cache()
    group_fleet_whitelist.save_group_fleet_whitelist([{"group_id": 100, "plugins": ["chat"]}])

    assert group_fleet_whitelist.add_group_fleet_whitelist_plugin(100, "ollama") is True
    assert group_fleet_whitelist.load_group_fleet_whitelist() == [
        {"group_id": 100, "plugins": ["chat", "ollama"]},
    ]
    assert group_fleet_whitelist.add_group_fleet_whitelist_plugin(100, "ollama") is False


def test_protected_plugins_cannot_be_whitelisted(tmp_path, monkeypatch):
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    group_fleet_whitelist.invalidate_group_fleet_whitelist_cache()

    saved = group_fleet_whitelist.save_group_fleet_whitelist([
        {"group_id": 100, "plugins": ["help", "ollama"]},
    ])
    assert saved == [{"group_id": 100, "plugins": ["ollama"]}]


def test_resolve_uses_mtime_cache_without_rereading_json(tmp_path, monkeypatch):
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    group_fleet_whitelist.save_group_fleet_whitelist([{"group_id": 100, "plugins": ["chat"]}])
    group_fleet_whitelist.invalidate_group_fleet_whitelist_cache()

    reads = {"n": 0}
    real_read = group_fleet_whitelist._read_whitelist_from_disk

    def counting_read():
        reads["n"] += 1
        return real_read()

    monkeypatch.setattr(group_fleet_whitelist, "_read_whitelist_from_disk", counting_read)

    assert group_fleet_whitelist.resolve_group_fleet_whitelist_plugins(100) == frozenset({"chat"})
    assert group_fleet_whitelist.resolve_group_fleet_whitelist_plugins(100) == frozenset({"chat"})
    assert reads["n"] == 1


def test_sync_remote_generation_invalidates_local_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    group_fleet_whitelist.save_group_fleet_whitelist([{"group_id": 100, "plugins": ["chat"]}])

    class FakeRedis:
        def __init__(self):
            self.gen = 1

        def get(self, _key):
            return str(self.gen).encode()

        def incr(self, _key):
            self.gen += 1
            return self.gen

    fake = FakeRedis()
    monkeypatch.setattr(
        "src.platform.coord.redis_claim.get_coord_redis_client",
        lambda: fake,
    )
    group_fleet_whitelist.invalidate_group_fleet_whitelist_cache()
    group_fleet_whitelist._synced_redis_gen = 0

    first = group_fleet_whitelist.resolve_group_fleet_whitelist_plugins(100)
    assert first == frozenset({"chat"})

    group_fleet_whitelist.save_group_fleet_whitelist([{"group_id": 100, "plugins": ["ollama"]}])
    group_fleet_whitelist.invalidate_group_fleet_whitelist_cache()
    group_fleet_whitelist._synced_redis_gen = 0

    second = group_fleet_whitelist.resolve_group_fleet_whitelist_plugins(100)
    assert second == frozenset({"ollama"})


@pytest.mark.asyncio
async def test_collect_disabled_applies_group_fleet_whitelist(beanie_fixture, tmp_path, monkeypatch):
    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["ollama"])
    group_fleet_whitelist.save_group_fleet_whitelist([{"group_id": 626266902, "plugins": ["ollama"]}])

    merged = await plugin_manager.collect_disabled_plugin_names(10, 626266902, ignore_cache=True)
    assert "ollama" not in merged

    other_group = await plugin_manager.collect_disabled_plugin_names(10, 2000, ignore_cache=True)
    assert "ollama" in other_group


@pytest.mark.asyncio
async def test_is_fleet_runtime_disabled_respects_group_whitelist(tmp_path, monkeypatch):
    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["ollama"])
    group_fleet_whitelist.save_group_fleet_whitelist([{"group_id": 626266902, "plugins": ["ollama"]}])

    assert plugin_manager.is_fleet_runtime_disabled("ollama") is True
    assert plugin_manager.is_fleet_runtime_disabled("ollama", group_id=626266902) is False
    assert plugin_manager.is_fleet_runtime_disabled("ollama", group_id=2000) is True


@pytest.mark.asyncio
async def test_superuser_group_enable_adds_fleet_whitelist(tmp_path, monkeypatch):
    from src.plugins.help import plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["repeater"])

    class _FakeConfig:
        def __init__(self, disabled_plugins: list[str] | None = None):
            self.disabled_plugins = list(disabled_plugins or [])

    async def fake_get_group_config(group_id: int):
        return _FakeConfig(), False

    monkeypatch.setattr(plugin_manager, "get_group_config", fake_get_group_config)

    async def fake_is_plugin_globally_disabled(*_a, **_k):
        return False

    monkeypatch.setattr(plugin_manager, "is_plugin_globally_disabled", fake_is_plugin_globally_disabled)

    success, msg = await plugin_manager._handle_group_plugin_operation(
        "repeater", "牛牛复读", 12345, 88002, "enable", is_superuser=True
    )
    assert success is True
    assert "制约" not in (msg or "")
    assert group_fleet_whitelist.load_group_fleet_whitelist() == [
        {"group_id": 12345, "plugins": ["repeater"]},
    ]
    assert plugin_manager.is_fleet_runtime_disabled("repeater", group_id=12345) is False


@pytest.mark.asyncio
async def test_handle_group_plugin_operation_whitelist_allows_enable(tmp_path, monkeypatch):
    from src.plugins.help import plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["repeater"])
    group_fleet_whitelist.save_group_fleet_whitelist([{"group_id": 12345, "plugins": ["repeater"]}])

    class _FakeConfig:
        def __init__(self, disabled_plugins: list[str] | None = None):
            self.disabled_plugins = list(disabled_plugins or [])

    async def fake_get_group_config(group_id: int):
        return _FakeConfig(), False

    monkeypatch.setattr(plugin_manager, "get_group_config", fake_get_group_config)

    async def fake_is_plugin_globally_disabled(*_a, **_k):
        return False

    monkeypatch.setattr(plugin_manager, "is_plugin_globally_disabled", fake_is_plugin_globally_disabled)

    success, msg = await plugin_manager._handle_group_plugin_operation(
        "repeater", "牛牛复读", 12345, 88002, "enable"
    )
    assert success is True
    assert "制约" not in (msg or "")
