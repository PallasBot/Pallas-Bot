"""plugin_loader 对依赖插件重复注册（Plugin already exists）的处理。"""

from __future__ import annotations

from pallas.core.platform.bot_runtime import plugin_loader as pl


def test_load_plugin_module_treats_already_exists_as_loaded(monkeypatch):
    """依赖插件已被 require 注册时，load_plugin 抛 already exists 视为已加载。"""
    monkeypatch.setattr(
        pl.nonebot,
        "load_plugin",
        lambda _path: (_ for _ in ()).throw(
            RuntimeError("Plugin already exists: nonebot_plugin_localstore! Check your plugin name")
        ),
    )
    monkeypatch.setattr(pl.importlib.util, "find_spec", lambda _m: object())

    loaded_short: set[str] = set()
    ok = pl._load_plugin_module(
        "nonebot_plugin_localstore",
        role_label="unified",
        loaded_short=loaded_short,
    )

    assert ok is True
    assert pl._load_slot_key("nonebot_plugin_localstore") in loaded_short


def test_load_plugin_module_still_fails_on_other_error(monkeypatch):
    """非 already exists 的异常仍记为加载失败。"""
    failures: list[str] = []
    monkeypatch.setattr(pl.nonebot, "load_plugin", lambda _path: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(pl.importlib.util, "find_spec", lambda _m: object())
    monkeypatch.setattr(pl, "record_startup_plugin_load_failure", failures.append)

    loaded_short: set[str] = set()
    ok = pl._load_plugin_module(
        "nonebot_plugin_localstore",
        role_label="unified",
        loaded_short=loaded_short,
    )

    assert ok is False
    assert loaded_short == set()
    assert failures
