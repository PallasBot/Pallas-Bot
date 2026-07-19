from __future__ import annotations

import pytest

from packages.help import global_disable, plugin_manager


def test_save_and_load_global_disabled_plugins(tmp_path, monkeypatch):
    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.invalidate_global_disabled_cache()

    assert global_disable.load_global_disabled_plugins() == []

    saved = global_disable.save_global_disabled_plugins(["chat", "ollama", "chat"])
    assert saved == ["chat", "ollama"]
    assert global_disable.load_global_disabled_plugins() == ["chat", "ollama"]


def test_sync_remote_generation_invalidates_local_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["chat"])

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
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: fake,
    )
    global_disable.invalidate_global_disabled_cache()
    global_disable._synced_redis_gen = 0

    first = global_disable.resolve_global_disabled_plugin_names()
    assert first == frozenset({"chat"})

    global_disable.save_global_disabled_plugins(["ollama"])
    global_disable.invalidate_global_disabled_cache()
    global_disable._synced_redis_gen = 0

    second = global_disable.resolve_global_disabled_plugin_names()
    assert second == frozenset({"ollama"})


def test_resolve_avoids_repeated_redis_get_within_sync_window(tmp_path, monkeypatch):
    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["chat"])

    class FakeRedis:
        def __init__(self):
            self.gen = 1
            self.get_calls = 0

        def get(self, _key):
            self.get_calls += 1
            return str(self.gen).encode()

        def incr(self, _key):
            self.gen += 1
            return self.gen

    fake = FakeRedis()
    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: fake,
    )
    global_disable.invalidate_global_disabled_cache()
    global_disable._synced_redis_gen = 0

    assert global_disable.resolve_global_disabled_plugin_names() == frozenset({"chat"})
    assert global_disable.resolve_global_disabled_plugin_names() == frozenset({"chat"})
    assert fake.get_calls == 1


def test_protected_plugins_cannot_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.invalidate_global_disabled_cache()

    saved = global_disable.save_global_disabled_plugins(["help", "chat", "pb_webui"])
    assert saved == ["chat"]
    assert "help" not in global_disable.resolve_global_disabled_plugin_names()


def test_resolve_uses_mtime_cache_without_rereading_json(tmp_path, monkeypatch):
    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["chat"])
    global_disable.invalidate_global_disabled_cache()

    reads = {"n": 0}
    real_read = global_disable._read_disabled_names_from_disk

    def counting_read():
        reads["n"] += 1
        return real_read()

    monkeypatch.setattr(global_disable, "_read_disabled_names_from_disk", counting_read)

    assert global_disable.resolve_global_disabled_plugin_names() == frozenset({"chat"})
    assert global_disable.resolve_global_disabled_plugin_names() == frozenset({"chat"})
    assert reads["n"] == 1


def test_merge_global_disabled_plugin_names(tmp_path, monkeypatch):
    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["chat"])

    merged = plugin_manager.merge_global_disabled_plugin_names(frozenset({"repeater"}))
    assert merged == frozenset({"repeater", "chat"})


@pytest.mark.asyncio
async def test_collect_disabled_includes_global_without_pg(beanie_fixture, monkeypatch, tmp_path):
    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["chat"])

    merged = await plugin_manager.collect_disabled_plugin_names(1, 2, ignore_cache=True)
    assert "chat" in merged
