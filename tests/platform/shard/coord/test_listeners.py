from __future__ import annotations

import pytest

from src.platform.shard.coord.listeners import (
    coord_listener_should_start,
    coord_listener_starters,
)


def test_coord_listener_should_start_respects_global_disable(tmp_path, monkeypatch) -> None:
    from src.plugins.help import global_disable

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path / "help")
    global_disable.save_global_disabled_plugins(["dream"])

    assert not coord_listener_should_start("dream")
    assert coord_listener_should_start(None)


def test_coord_listener_starters_skips_disabled_plugin(tmp_path, monkeypatch) -> None:
    from src.plugins.help import global_disable

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path / "help")
    global_disable.save_global_disabled_plugins(["dream"])

    names = {getattr(fn, "__module__", "") for fn in coord_listener_starters()}
    assert not any("dream_drift" in n for n in names)
    assert any("bot_action" in n for n in names)
