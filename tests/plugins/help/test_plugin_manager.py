"""
Tests for src/plugins/help/plugin_manager.py after refactor to Repository.

覆盖 BotConfig/GroupConfig 的读写是否全部走 repo，不再直调 Beanie Document。
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_is_plugin_disabled_creates_bot_config_on_first_access(beanie_fixture):
    from src.plugins.help import plugin_manager

    # 首次查询时 bot config 不存在，函数应 auto-create
    result = await plugin_manager.is_plugin_disabled("foo", bot_id=12345)
    assert result is False

    bot_cfg = await plugin_manager.bot_config_repo.get(12345, ignore_cache=True)
    assert bot_cfg is not None
    assert bot_cfg.disabled_plugins == []


@pytest.mark.asyncio
async def test_is_plugin_disabled_globally_disabled(beanie_fixture):
    from src.plugins.help import plugin_manager

    await plugin_manager.bot_config_repo.upsert_field(99, "disabled_plugins", ["bad_plugin"])
    assert await plugin_manager.is_plugin_disabled("bad_plugin", bot_id=99) is True
    assert await plugin_manager.is_plugin_disabled("good_plugin", bot_id=99) is False


@pytest.mark.asyncio
async def test_is_plugin_disabled_group_level(beanie_fixture):
    from src.plugins.help import plugin_manager

    await plugin_manager.group_config_repo.upsert_field(101, "disabled_plugins", ["chat"])
    assert await plugin_manager.is_plugin_disabled("chat", group_id=101, bot_id=1) is True
    assert await plugin_manager.is_plugin_disabled("other", group_id=101, bot_id=1) is False


@pytest.mark.asyncio
async def test_is_plugin_globally_disabled(beanie_fixture):
    from src.plugins.help import plugin_manager

    assert await plugin_manager.is_plugin_globally_disabled("x", bot_id=500) is False
    await plugin_manager.bot_config_repo.upsert_field(500, "disabled_plugins", ["x"])
    assert await plugin_manager.is_plugin_globally_disabled("x", bot_id=500) is True


@pytest.mark.asyncio
async def test_get_bot_config_creates_if_missing(beanie_fixture):
    from src.plugins.help import plugin_manager

    cfg, created = await plugin_manager.get_bot_config(777)
    assert created is True
    assert cfg.account == 777

    cfg2, created2 = await plugin_manager.get_bot_config(777)
    assert created2 is False
    assert cfg2.account == 777


@pytest.mark.asyncio
async def test_get_group_config_creates_if_missing(beanie_fixture):
    from src.plugins.help import plugin_manager

    cfg, created = await plugin_manager.get_group_config(8888)
    assert created is True
    assert cfg.group_id == 8888


@pytest.mark.asyncio
async def test_update_bot_config_roundtrip(beanie_fixture, tmp_path, monkeypatch):
    from src.plugins.help import plugin_manager

    # 避免真实改 help 缓存目录
    monkeypatch.setattr(plugin_manager, "clear_help_cache", lambda *a, **k: None)

    await plugin_manager.get_bot_config(123)
    updated = await plugin_manager.update_bot_config(123, ["p1", "p2"])
    assert updated.disabled_plugins == ["p1", "p2"]

    # 再次验证读 path
    cfg = await plugin_manager.bot_config_repo.get(123, ignore_cache=True)
    assert cfg is not None
    assert cfg.disabled_plugins == ["p1", "p2"]


@pytest.mark.asyncio
async def test_update_group_config_roundtrip(beanie_fixture, monkeypatch):
    from src.plugins.help import plugin_manager

    monkeypatch.setattr(plugin_manager, "clear_help_cache", lambda *a, **k: None)

    await plugin_manager.get_group_config(321)
    updated = await plugin_manager.update_group_config(321, ["p3"])
    assert updated.disabled_plugins == ["p3"]
