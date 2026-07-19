from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_community_install_hot_loads_in_unified(monkeypatch):
    from pallas.console.cli import community_plugin_ops

    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.resolve_bot_mode",
        lambda _mode: "unified",
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.hot_load_extra_dir_plugin",
        lambda _plugin_id: True,
    )
    monkeypatch.setattr(
        community_plugin_ops,
        "install_community_plugin",
        AsyncMock(
            return_value={
                "plugin_id": "interact",
                "installed": True,
                "needs_restart": True,
                "extra_plugin_dirs_ready": True,
                "message": "已安装到 local/plugins/interact/。",
            },
        ),
    )
    out = await community_plugin_ops.install_community_plugin_with_options(
        "interact",
        repository_url="https://github.com/example/interact",
        restart=False,
    )
    assert out["activation_action"] == "hot-reload"
    assert out["needs_restart"] is False
    assert "已在当前进程直接加载" in str(out.get("message"))


@pytest.mark.asyncio
async def test_community_install_shard_pending_without_restart(monkeypatch):
    from pallas.console.cli import community_plugin_ops

    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.resolve_bot_mode",
        lambda _mode: "shard",
    )
    monkeypatch.setattr(
        community_plugin_ops,
        "install_community_plugin",
        AsyncMock(
            return_value={
                "plugin_id": "interact",
                "installed": True,
                "needs_restart": True,
                "extra_plugin_dirs_ready": True,
                "message": "已安装到 local/plugins/interact/。",
            },
        ),
    )
    out = await community_plugin_ops.install_community_plugin_with_options(
        "interact",
        repository_url="https://github.com/example/interact",
        restart=False,
    )
    assert out["activation_action"] == "none"
    assert out["needs_restart"] is True
    assert "重启" in str(out.get("message"))


@pytest.mark.asyncio
async def test_community_install_with_restart_schedules_workers_only(monkeypatch):
    from pallas.console.cli import community_plugin_ops

    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.resolve_bot_mode",
        lambda _mode: "shard",
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.schedule_bot_restart",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        community_plugin_ops,
        "install_community_plugin",
        AsyncMock(
            return_value={
                "plugin_id": "interact",
                "installed": True,
                "needs_restart": True,
                "extra_plugin_dirs_ready": True,
                "message": "已安装到 local/plugins/interact/。",
            },
        ),
    )
    out = await community_plugin_ops.install_community_plugin_with_options(
        "interact",
        repository_url="https://github.com/example/interact",
        restart=True,
    )
    assert out["restart_scheduled"] is True
    assert out["activation_action"] == "workers-restart"
    assert calls == [{"mode": "shard", "workers_only": True}]


@pytest.mark.asyncio
async def test_community_update_with_restart_schedules_workers_only(monkeypatch):
    from pallas.console.cli import community_plugin_ops

    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.resolve_bot_mode",
        lambda _mode: "shard",
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.schedule_bot_restart",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        community_plugin_ops,
        "update_community_plugin",
        AsyncMock(
            return_value={
                "plugin_id": "interact",
                "installed": True,
                "needs_restart": True,
                "extra_plugin_dirs_ready": True,
                "message": "已更新 local/plugins/interact/。",
            },
        ),
    )
    out = await community_plugin_ops.update_community_plugin_with_options(
        "interact",
        restart=True,
    )
    assert out["activation_policy"] == "workers-restart"
    assert out["restart_scheduled"] is True
    assert out["activation_action"] == "workers-restart"
    assert calls == [{"mode": "shard", "workers_only": True}]


@pytest.mark.asyncio
async def test_community_install_hot_load_failure_falls_back_to_restart(monkeypatch):
    from pallas.console.cli import community_plugin_ops

    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.resolve_bot_mode",
        lambda _mode: "unified",
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.hot_load_extra_dir_plugin",
        lambda _plugin_id: False,
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.schedule_bot_restart",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        community_plugin_ops,
        "install_community_plugin",
        AsyncMock(
            return_value={
                "plugin_id": "interact",
                "installed": True,
                "needs_restart": True,
                "extra_plugin_dirs_ready": True,
                "message": "已安装到 local/plugins/interact/。",
            },
        ),
    )
    out = await community_plugin_ops.install_community_plugin_with_options(
        "interact",
        repository_url="https://github.com/example/interact",
        restart=True,
    )
    assert out.get("hot_load_fallback") is True
    assert out["restart_scheduled"] is True
    assert out["activation_action"] == "full-restart"
    assert calls == [{"mode": "unified", "workers_only": False}]
    assert "热加载失败" in str(out.get("message"))


@pytest.mark.asyncio
async def test_community_update_pending_note_without_restart(monkeypatch):
    from pallas.console.cli import community_plugin_ops

    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.resolve_bot_mode",
        lambda _mode: "unified",
    )
    monkeypatch.setattr(
        community_plugin_ops,
        "update_community_plugin",
        AsyncMock(
            return_value={
                "plugin_id": "interact",
                "installed": True,
                "needs_restart": True,
                "extra_plugin_dirs_ready": True,
                "message": "已更新 local/plugins/interact/。",
            },
        ),
    )
    out = await community_plugin_ops.update_community_plugin_with_options(
        "interact",
        restart=False,
    )
    assert out["activation_policy"] == "workers-restart"
    assert out["needs_restart"] is True
    assert "不支持运行时热更" in str(out.get("message"))


@pytest.mark.asyncio
async def test_community_uninstall_pending_note_without_restart(monkeypatch):
    from pallas.console.cli import community_plugin_ops

    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_activation.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        community_plugin_ops,
        "uninstall_community_plugin",
        AsyncMock(
            return_value={
                "plugin_id": "interact",
                "installed": False,
                "needs_restart": True,
                "message": "已删除 local/plugins/interact/。",
            },
        ),
    )
    out = await community_plugin_ops.uninstall_community_plugin_with_options(
        "interact",
        restart=False,
    )
    assert out["activation_policy"] == "full-restart"
    assert "matcher" in str(out.get("message"))
