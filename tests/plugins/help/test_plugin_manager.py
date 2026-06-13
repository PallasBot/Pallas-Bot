"""
Tests for src/plugins/help/plugin_manager.py after refactor to Repository.

覆盖 BotConfig/GroupConfig 的读写是否全部走 repo，不再直调 Beanie Document。
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
async def beanie_fixture():
    dsn = os.getenv("PG_TEST_DSN")
    if not dsn:
        pytest.skip("需要设置 PG_TEST_DSN 指向测试 PG 实例")

    from sqlalchemy.ext.asyncio import create_async_engine

    from src.foundation.db.repository_pg import Base, dispose_pg, init_pg

    engine = create_async_engine(dsn)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_pg(engine)
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await dispose_pg()


@pytest.mark.asyncio
async def test_is_plugin_disabled_does_not_create_bot_config(beanie_fixture):
    from src.plugins.help import plugin_manager

    result = await plugin_manager.is_plugin_disabled("foo", bot_id=12345)
    assert result is False

    bot_cfg = await plugin_manager.bot_config_repo.get(12345, ignore_cache=True)
    assert bot_cfg is None


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


@pytest.mark.asyncio
async def test_collect_disabled_plugin_names_merges_bot_and_group(beanie_fixture, tmp_path, monkeypatch):
    from src.plugins.help import global_disable, plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)

    await plugin_manager.bot_config_repo.upsert_field(10, "disabled_plugins", ["g"])
    await plugin_manager.group_config_repo.upsert_field(2000, "disabled_plugins", ["c"])
    merged = await plugin_manager.collect_disabled_plugin_names(10, 2000, ignore_cache=True)
    assert merged == frozenset({"g", "c"})
    for name in ("g", "c", "other"):
        exp = await plugin_manager.is_plugin_disabled(name, group_id=2000, bot_id=10, ignore_cache=True)
        assert (name in merged) is exp


@pytest.mark.asyncio
async def test_collect_disabled_plugin_names_merges_global(beanie_fixture, tmp_path, monkeypatch):
    from src.plugins.help import global_disable, plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["ollama"])

    await plugin_manager.bot_config_repo.upsert_field(10, "disabled_plugins", ["g"])
    await plugin_manager.group_config_repo.upsert_field(2000, "disabled_plugins", ["c"])
    merged = await plugin_manager.collect_disabled_plugin_names(10, 2000, ignore_cache=True)
    assert merged == frozenset({"g", "c", "ollama"})


@pytest.mark.asyncio
async def test_collect_disabled_plugin_names_bot_only(beanie_fixture):
    from src.plugins.help import plugin_manager

    merged = await plugin_manager.collect_disabled_plugin_names(30001, None, ignore_cache=True)
    assert merged == frozenset()
    assert await plugin_manager.is_plugin_disabled("x", group_id=None, bot_id=30001, ignore_cache=True) is False


@pytest.mark.asyncio
async def test_collect_disabled_plugin_names_gate_cache(beanie_fixture, monkeypatch):
    from src.plugins.help import plugin_manager

    await plugin_manager.reset_disabled_plugin_gate_cache()
    bot_calls: list[int] = []
    group_calls: list[int] = []
    real_load_bot = plugin_manager.load_disabled_bot_names_from_db
    real_load_group = plugin_manager.load_disabled_group_names_from_db

    async def counting_load_bot(bot_id, *, ignore_cache=False):
        bot_calls.append(int(bot_id))
        return await real_load_bot(bot_id, ignore_cache=ignore_cache)

    async def counting_load_group(group_id, *, ignore_cache=False):
        group_calls.append(int(group_id))
        return await real_load_group(group_id, ignore_cache=ignore_cache)

    monkeypatch.setattr(plugin_manager, "load_disabled_bot_names_from_db", counting_load_bot)
    monkeypatch.setattr(plugin_manager, "load_disabled_group_names_from_db", counting_load_group)

    await plugin_manager.bot_config_repo.upsert_field(77, "disabled_plugins", ["a"])
    first = await plugin_manager.collect_disabled_plugin_names(77, 5001)
    second = await plugin_manager.collect_disabled_plugin_names(77, 5001)
    assert first == frozenset({"a"})
    assert second == frozenset({"a"})
    assert bot_calls == [77]
    assert group_calls == [5001]

    await plugin_manager.invalidate_disabled_plugin_gate_cache(bot_id=77)
    third = await plugin_manager.collect_disabled_plugin_names(77, 5001)
    assert third == frozenset({"a"})
    assert bot_calls == [77, 77]
    assert group_calls == [5001]

    await plugin_manager.reset_disabled_plugin_gate_cache()


@pytest.mark.asyncio
async def test_collect_disabled_plugin_names_reuses_bot_scope_across_groups(beanie_fixture, monkeypatch):
    from src.plugins.help import plugin_manager

    await plugin_manager.reset_disabled_plugin_gate_cache()
    await plugin_manager.bot_config_repo.upsert_field(901, "disabled_plugins", ["a"])

    calls: list[int] = []
    real_get = plugin_manager.bot_config_repo.get

    async def counting_get(bot_id, *, ignore_cache=False):
        calls.append(int(bot_id))
        return await real_get(bot_id, ignore_cache=ignore_cache)

    monkeypatch.setattr(plugin_manager.bot_config_repo, "get", counting_get)

    first = await plugin_manager.collect_disabled_plugin_names(901, 5001)
    second = await plugin_manager.collect_disabled_plugin_names(901, 5002)

    assert first == frozenset({"a"})
    assert second == frozenset({"a"})
    assert calls == [901]

    await plugin_manager.reset_disabled_plugin_gate_cache()


@pytest.mark.asyncio
async def test_collect_disabled_plugin_names_does_not_create_empty_bot_config(beanie_fixture):
    from src.plugins.help import plugin_manager

    await plugin_manager.reset_disabled_plugin_gate_cache()

    bot_id = 30002
    merged = await plugin_manager.collect_disabled_plugin_names(bot_id, None, ignore_cache=True)

    assert merged == frozenset()
    assert await plugin_manager.bot_config_repo.get(bot_id, ignore_cache=True) is None


@pytest.mark.asyncio
async def test_collect_disabled_plugin_names_short_circuits_when_pg_not_ready(monkeypatch, tmp_path):
    from src.plugins.help import global_disable, plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["chat"])
    await plugin_manager.reset_disabled_plugin_gate_cache()

    async def fail_load(bot_id, group_id, *, ignore_cache=False):  # noqa: ARG001
        raise AssertionError("should not load disabled plugin names when PG is not ready")

    monkeypatch.setattr(plugin_manager, "load_disabled_plugin_names_from_db", fail_load)
    monkeypatch.setattr("src.foundation.db.get_db_backend", lambda: "postgresql")
    monkeypatch.setattr("src.foundation.db.repository_pg.is_pg_initialized", lambda: False)

    merged = await plugin_manager.collect_disabled_plugin_names(77, 5001)
    assert merged == frozenset({"chat"})


@pytest.mark.asyncio
async def test_fill_plugin_status_reuses_disabled_plugin_gate_cache(beanie_fixture, monkeypatch):
    from src.plugins.help import plugin_manager

    await plugin_manager.reset_disabled_plugin_gate_cache()

    calls: list[bool] = []

    async def counting_collect(bot_id, group_id, *, ignore_cache=False):
        calls.append(bool(ignore_cache))
        assert bot_id == 1234
        assert group_id == 5678
        return frozenset({"chat"})

    monkeypatch.setattr(plugin_manager, "collect_disabled_plugin_names", counting_collect)
    monkeypatch.setattr(
        plugin_manager,
        "get_help_menu_plugins",
        lambda **_kwargs: [
            type("Plugin", (), {"name": "chat"})(),
            type("Plugin", (), {"name": "other"})(),
        ],
    )
    monkeypatch.setattr(plugin_manager, "apply_status_marks_to_plugin_table", lambda content, _marks: content)
    monkeypatch.setattr(
        "src.plugins.help.markdown_generator.help_list_status_mark",
        lambda enabled: "Y" if enabled else "N",
    )

    await plugin_manager.fill_plugin_status("|1|?|chat|\n|2|?|other|", bot_id=1234, group_id=5678)

    assert calls == [False]


@pytest.mark.asyncio
async def test_load_disabled_group_names_reads_repo_directly(beanie_fixture, monkeypatch):
    from src.plugins.help import plugin_manager

    await plugin_manager.reset_disabled_plugin_gate_cache()

    calls: list[tuple[int, bool]] = []

    async def fake_get(group_id: int, *, ignore_cache: bool = False):
        calls.append((group_id, ignore_cache))
        return type("GroupCfg", (), {"disabled_plugins": ["chat"]})()

    monkeypatch.setattr(plugin_manager.group_config_repo, "get", fake_get)

    got = await plugin_manager.load_disabled_group_names_from_db(7654)

    assert got == frozenset({"chat"})
    assert calls == [(7654, False)]


@pytest.mark.asyncio
async def test_load_disabled_group_names_returns_empty_when_repo_missing(beanie_fixture, monkeypatch):
    from src.plugins.help import plugin_manager

    await plugin_manager.reset_disabled_plugin_gate_cache()

    async def fake_get(group_id: int, *, ignore_cache: bool = False):
        assert group_id == 4567
        assert ignore_cache is False
        return None

    monkeypatch.setattr(plugin_manager.group_config_repo, "get", fake_get)

    got = await plugin_manager.load_disabled_group_names_from_db(4567)
    assert got == frozenset()


class _FakeConfig:
    def __init__(self, disabled_plugins: list[str] | None = None):
        self.disabled_plugins = list(disabled_plugins or [])


@pytest.mark.asyncio
async def test_handle_global_plugin_operation_fleet_constraint(tmp_path, monkeypatch):
    from src.plugins.help import global_disable, plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["repeater"])

    async def fake_get_bot_config(bot_id: int):
        return _FakeConfig(), False

    monkeypatch.setattr(plugin_manager, "get_bot_config", fake_get_bot_config)

    success, msg = await plugin_manager._handle_global_plugin_operation("repeater", "牛牛复读", 88001, "enable")
    assert success is True
    assert msg == "牛牛复读 受到了米诺斯的制约..."


@pytest.mark.asyncio
async def test_handle_global_plugin_operation_fleet_constraint_skips_config_update(tmp_path, monkeypatch):
    from src.plugins.help import global_disable, plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["repeater"])

    config = _FakeConfig(["repeater"])
    updated = False

    async def fake_get_bot_config(bot_id: int):
        return config, False

    async def fake_update_config_and_cache(*_args, **_kwargs):
        nonlocal updated
        updated = True
        return True, config

    monkeypatch.setattr(plugin_manager, "get_bot_config", fake_get_bot_config)
    monkeypatch.setattr(plugin_manager, "update_config_and_cache", fake_update_config_and_cache)

    await plugin_manager._handle_global_plugin_operation("repeater", "牛牛复读", 88001, "enable")
    assert updated is False


@pytest.mark.asyncio
async def test_handle_group_plugin_operation_fleet_constraint(tmp_path, monkeypatch):
    from src.plugins.help import global_disable, group_fleet_whitelist, plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    group_fleet_whitelist.invalidate_group_fleet_whitelist_cache()
    global_disable.save_global_disabled_plugins(["repeater"])

    async def fake_get_group_config(group_id: int):
        return _FakeConfig(), False

    monkeypatch.setattr(plugin_manager, "get_group_config", fake_get_group_config)

    async def fake_is_plugin_globally_disabled(*_a, **_k):
        return False

    monkeypatch.setattr(plugin_manager, "is_plugin_globally_disabled", fake_is_plugin_globally_disabled)

    success, msg = await plugin_manager._handle_group_plugin_operation("repeater", "牛牛复读", 12345, 88002, "enable")
    assert success is True
    assert msg == "博士，牛牛复读 受到了米诺斯的制约..."


@pytest.mark.asyncio
async def test_handle_global_plugin_operation_fleet_constraint_superuser_exempt(tmp_path, monkeypatch):
    from src.plugins.help import global_disable, plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    global_disable.save_global_disabled_plugins(["repeater"])

    async def fake_get_bot_config(bot_id: int):
        return _FakeConfig(), False

    monkeypatch.setattr(plugin_manager, "get_bot_config", fake_get_bot_config)

    success, msg = await plugin_manager._handle_global_plugin_operation(
        "repeater", "牛牛复读", 88001, "enable", is_superuser=True
    )
    assert success is True
    assert "制约" not in (msg or "")


@pytest.mark.asyncio
async def test_handle_group_plugin_operation_bot_disable_superuser_exempt(monkeypatch):
    from src.plugins.help import plugin_manager

    async def fake_get_group_config(group_id: int):
        return _FakeConfig(), False

    async def fake_is_plugin_globally_disabled(*_a, **_k):
        return True

    monkeypatch.setattr(plugin_manager, "get_group_config", fake_get_group_config)
    monkeypatch.setattr(plugin_manager, "is_plugin_globally_disabled", fake_is_plugin_globally_disabled)
    monkeypatch.setattr(plugin_manager, "is_fleet_runtime_disabled", lambda *_a, **_k: False)

    success, msg = await plugin_manager._handle_group_plugin_operation(
        "repeater", "牛牛复读", 12345, 88002, "enable", is_superuser=True
    )
    assert success is True
    assert "制约" not in (msg or "")


@pytest.mark.asyncio
async def test_handle_group_plugin_operation_fleet_constraint_superuser_exempt(tmp_path, monkeypatch):
    from src.plugins.help import global_disable, group_fleet_whitelist, plugin_manager

    monkeypatch.setattr(global_disable, "plugin_data_dir", lambda _name: tmp_path)
    monkeypatch.setattr(group_fleet_whitelist, "plugin_data_dir", lambda _name: tmp_path)
    group_fleet_whitelist.invalidate_group_fleet_whitelist_cache()
    global_disable.save_global_disabled_plugins(["repeater"])

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
