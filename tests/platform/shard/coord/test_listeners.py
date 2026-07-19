from __future__ import annotations

import pytest

import packages.help  # noqa: F401
from pallas.core.platform.shard.coord.listeners import (
    coord_listener_should_start,
    coord_listener_starters,
)
from pallas.core.storage.schema import clear_plugin_storage_registry_cache


@pytest.fixture(autouse=True)
def register_help_plugin_storage(monkeypatch):
    class FakePlugin:
        name = "help"
        metadata = packages.help.__plugin_meta__

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakePlugin()])
    clear_plugin_storage_registry_cache()
    yield
    clear_plugin_storage_registry_cache()


def test_coord_listener_should_start_respects_global_disable(tmp_path, monkeypatch) -> None:
    from packages.help import global_disable

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path / "help")
    global_disable.save_global_disabled_plugins(["dream"])

    assert not coord_listener_should_start("dream")
    assert coord_listener_should_start(None)


def test_coord_listener_starters_skips_disabled_plugin(tmp_path, monkeypatch) -> None:
    from packages.help import global_disable

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path / "help")
    global_disable.save_global_disabled_plugins(["dream"])

    names = {getattr(fn, "__module__", "") for fn in coord_listener_starters()}
    assert not any("dream_drift" in n for n in names)
    assert any("bot_action" in n for n in names)
