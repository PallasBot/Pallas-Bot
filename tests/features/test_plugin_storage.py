from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.core.storage.declare import plugin_storage_row
from pallas.core.storage.metadata import parse_plugin_storage_decl
from pallas.core.storage.schema import clear_plugin_storage_registry_cache
from pallas.core.storage.store import (
    GroupPluginStorage,
    PluginStorageKeyError,
    clear_ephemeral_plugin_storage,
    get_plugin_storage,
    set_plugin_storage,
)


@pytest.fixture(autouse=True)
def reset_storage() -> None:
    clear_ephemeral_plugin_storage()
    clear_plugin_storage_registry_cache()
    yield
    clear_ephemeral_plugin_storage()
    clear_plugin_storage_registry_cache()


def test_parse_plugin_storage_decl() -> None:
    decl = parse_plugin_storage_decl(
        plugin_storage_row("duel_pair", scope="group", label="配对", ephemeral=True),
    )
    assert decl is not None
    assert decl.key == "duel_pair"
    assert decl.ephemeral is True


@pytest.mark.asyncio
async def test_ephemeral_group_storage(monkeypatch) -> None:
    class FakePlugin:
        name = "duel"
        metadata = SimpleNamespace(
            name="决斗",
            extra={
                "plugin_storage": [
                    plugin_storage_row("duel_pair", ephemeral=True),
                ]
            },
        )

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakePlugin()])
    clear_plugin_storage_registry_cache()

    await set_plugin_storage("duel", "duel_pair", {"a": 1, "b": 2, "until": 9}, scope_id=100)
    value = await get_plugin_storage("duel", "duel_pair", scope_id=100)
    assert value == {"a": 1, "b": 2, "until": 9}

    store = GroupPluginStorage("duel", 100)
    await store.delete("duel_pair")
    assert await store.get("duel_pair") is None


@pytest.mark.asyncio
async def test_persisted_group_storage(monkeypatch) -> None:
    persisted: dict[int, dict] = {}

    class FakePlugin:
        name = "demo"
        metadata = SimpleNamespace(
            name="演示",
            extra={
                "plugin_storage": [
                    plugin_storage_row("counter", ephemeral=False),
                ]
            },
        )

    async def fake_find(_self, key: str):
        if key != "plugin_storage":
            return None
        return persisted.get(200, {})

    async def fake_update(_self, key: str, value):
        if key == "plugin_storage":
            persisted[200] = value

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakePlugin()])
    monkeypatch.setattr("pallas.core.foundation.config.GroupConfig._find", fake_find)
    monkeypatch.setattr("pallas.core.foundation.config.GroupConfig._update", fake_update)
    clear_plugin_storage_registry_cache()

    await set_plugin_storage("demo", "counter", 3, scope_id=200)
    assert await get_plugin_storage("demo", "counter", scope_id=200) == 3
    assert persisted[200]["demo"]["counter"] == 3


@pytest.mark.asyncio
async def test_deploy_scope_async(monkeypatch, tmp_path) -> None:
    class FakePlugin:
        name = "demo"
        metadata = SimpleNamespace(
            name="演示",
            extra={
                "plugin_storage": [
                    plugin_storage_row("note", scope="deploy"),
                ]
            },
        )

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakePlugin()])
    monkeypatch.setattr(
        "pallas.core.storage.deploy_store.plugin_data_dir",
        lambda _name: tmp_path / "demo",
    )
    clear_plugin_storage_registry_cache()

    await set_plugin_storage("demo", "note", "hello", scope_id=0, scope="deploy")
    assert await get_plugin_storage("demo", "note", scope_id=0, scope="deploy") == "hello"


@pytest.mark.asyncio
async def test_undeclared_key_rejected(monkeypatch) -> None:
    monkeypatch.setattr("nonebot.get_loaded_plugins", list)
    clear_plugin_storage_registry_cache()
    with pytest.raises(PluginStorageKeyError):
        await get_plugin_storage("missing", "x", scope_id=1)
