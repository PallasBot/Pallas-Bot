from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_install_with_restart_schedules_workers_only(monkeypatch):
    from pallas.console.cli import extension_ops

    calls: list[dict[str, object]] = []

    monkeypatch.setattr("pallas.console.cli.extension_activation.bot_lifecycle_available", lambda: True)
    monkeypatch.setattr("pallas.console.cli.extension_activation.resolve_bot_mode", lambda _mode: "shard")
    monkeypatch.setattr(
        "pallas.console.cli.extension_activation.schedule_bot_restart",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        extension_ops,
        "install_official_extension",
        AsyncMock(
            return_value={
                "package": "pallas-plugin-duel",
                "needs_restart": True,
                "message": "安装完成",
            },
        ),
    )
    out = await extension_ops.install_official_extension_with_options(
        "pallas-plugin-duel",
        restart=True,
    )
    assert out["restart_scheduled"] is True
    assert out["activation_action"] == "workers-restart"
    assert calls == [{"mode": "shard", "workers_only": True}]
    assert "worker" in str(out.get("message"))


@pytest.mark.asyncio
async def test_install_with_restart_schedules_full_restart(monkeypatch):
    from pallas.console.cli import extension_ops

    calls: list[dict[str, object]] = []

    monkeypatch.setattr("pallas.console.cli.extension_activation.bot_lifecycle_available", lambda: True)
    monkeypatch.setattr("pallas.console.cli.extension_activation.resolve_bot_mode", lambda _mode: "shard")
    monkeypatch.setattr(
        "pallas.console.cli.extension_activation.schedule_bot_restart",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        extension_ops,
        "install_official_extension",
        AsyncMock(
            return_value={
                "package": "pallas-plugin-maa",
                "needs_restart": True,
                "message": "安装完成",
            },
        ),
    )
    out = await extension_ops.install_official_extension_with_options(
        "pallas-plugin-maa",
        restart=True,
    )
    assert out["restart_scheduled"] is True
    assert out["activation_action"] == "full-restart"
    assert calls == [{"mode": "shard", "workers_only": False}]
    assert "重启" in str(out.get("message"))


@pytest.mark.asyncio
async def test_install_without_restart_uses_policy_pending_note(monkeypatch):
    from pallas.console.cli import extension_ops

    monkeypatch.setattr("pallas.console.cli.extension_activation.bot_lifecycle_available", lambda: True)
    monkeypatch.setattr("pallas.console.cli.extension_activation.resolve_bot_mode", lambda _mode: "shard")
    monkeypatch.setattr(
        extension_ops,
        "install_official_extension",
        AsyncMock(
            return_value={
                "package": "pallas-plugin-draw",
                "needs_restart": True,
                "message": "安装完成。",
            },
        ),
    )
    out = await extension_ops.install_official_extension_with_options(
        "pallas-plugin-draw",
        restart=False,
    )
    assert out["activation_policy"] == "hot-reloadable"
    assert out["activation_action"] == "none"
    assert "热加载" in str(out.get("message"))
    assert "重启" in str(out.get("message"))


@pytest.mark.asyncio
async def test_install_without_restart_workers_restart_note(monkeypatch):
    from pallas.console.cli import extension_ops

    monkeypatch.setattr("pallas.console.cli.extension_activation.bot_lifecycle_available", lambda: True)
    monkeypatch.setattr(
        extension_ops,
        "install_official_extension",
        AsyncMock(
            return_value={
                "package": "pallas-plugin-duel",
                "needs_restart": True,
                "message": "安装完成。",
            },
        ),
    )
    out = await extension_ops.install_official_extension_with_options(
        "pallas-plugin-duel",
        restart=False,
    )
    assert out["activation_policy"] == "workers-restart"
    assert "Worker" in str(out.get("message"))


@pytest.mark.asyncio
async def test_install_without_restart_hot_loads_in_unified(monkeypatch):
    from pallas.console.cli import extension_ops

    monkeypatch.setattr("pallas.console.cli.extension_activation.bot_lifecycle_available", lambda: True)
    monkeypatch.setattr("pallas.console.cli.extension_activation.resolve_bot_mode", lambda _mode: "unified")
    monkeypatch.setattr("pallas.console.cli.extension_activation._hot_load_package_modules", lambda _package: True)
    monkeypatch.setattr(
        extension_ops,
        "install_official_extension",
        AsyncMock(
            return_value={
                "package": "pallas-plugin-bot-status",
                "needs_restart": True,
                "message": "安装完成。",
            },
        ),
    )
    out = await extension_ops.install_official_extension_with_options(
        "pallas-plugin-bot-status",
        restart=False,
    )
    assert out["activation_action"] == "hot-reload"
    assert out["needs_restart"] is False
    assert "直接加载" in str(out.get("message"))


@pytest.mark.asyncio
async def test_install_hot_load_failure_falls_back_to_restart(monkeypatch):
    from pallas.console.cli import extension_ops

    calls: list[dict[str, object]] = []
    monkeypatch.setattr("pallas.console.cli.extension_activation.bot_lifecycle_available", lambda: True)
    monkeypatch.setattr("pallas.console.cli.extension_activation.resolve_bot_mode", lambda _mode: "unified")
    monkeypatch.setattr("pallas.console.cli.extension_activation._hot_load_package_modules", lambda _package: False)
    monkeypatch.setattr(
        "pallas.console.cli.extension_activation.schedule_bot_restart",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        extension_ops,
        "install_official_extension",
        AsyncMock(
            return_value={
                "package": "pallas-plugin-draw",
                "needs_restart": True,
                "message": "安装完成",
            },
        ),
    )
    out = await extension_ops.install_official_extension_with_options(
        "pallas-plugin-draw",
        restart=True,
    )
    assert out["restart_scheduled"] is True
    assert out["activation_action"] == "full-restart"
    assert out.get("hot_load_fallback") is True
    assert calls == [{"mode": "unified", "workers_only": False}]
    assert "热加载失败" in str(out.get("message"))


@pytest.mark.asyncio
async def test_install_with_restart_hot_loads_in_unified(monkeypatch):
    from pallas.console.cli import extension_ops

    monkeypatch.setattr("pallas.console.cli.extension_activation.bot_lifecycle_available", lambda: True)
    monkeypatch.setattr("pallas.console.cli.extension_activation.resolve_bot_mode", lambda _mode: "unified")
    monkeypatch.setattr("pallas.console.cli.extension_activation._hot_load_package_modules", lambda _package: True)
    monkeypatch.setattr(
        extension_ops,
        "install_official_extension",
        AsyncMock(
            return_value={
                "package": "pallas-plugin-draw",
                "needs_restart": True,
                "message": "安装完成",
            },
        ),
    )
    out = await extension_ops.install_official_extension_with_options(
        "pallas-plugin-draw",
        restart=True,
    )
    assert out["restart_scheduled"] is False
    assert out["activation_action"] == "hot-reload"
    assert out["needs_restart"] is False
    assert "直接加载" in str(out.get("message"))
