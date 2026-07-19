from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_resolve_community_plugin_target_from_index(monkeypatch) -> None:
    from pallas.console.cli.community_plugin_target import resolve_community_plugin_target

    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_index.load_community_plugin_index_safe",
        AsyncMock(
            return_value={
                "plugins": [
                    {
                        "plugin_id": "interact",
                        "repository_url": "https://github.com/PallasBot/interact.git",
                        "ref": "main",
                    },
                ],
            },
        ),
    )
    pid, repo, ref = await resolve_community_plugin_target("interact")
    assert pid == "interact"
    assert repo == "https://github.com/PallasBot/interact.git"
    assert ref == "main"


@pytest.mark.asyncio
async def test_resolve_community_plugin_target_explicit_repo() -> None:
    from pallas.console.cli.community_plugin_target import resolve_community_plugin_target

    pid, repo, ref = await resolve_community_plugin_target(
        "interact",
        repository_url="https://github.com/example/interact.git",
        ref="dev",
    )
    assert pid == "interact"
    assert repo == "https://github.com/example/interact.git"
    assert ref == "dev"


@pytest.mark.asyncio
async def test_cli_install_uses_community_plugin_ops(monkeypatch) -> None:
    from pallas.console.cli.commands import community_plugin_cmd

    monkeypatch.setattr(
        "pallas.console.cli.community_plugin_target.resolve_community_plugin_target",
        AsyncMock(return_value=("interact", "https://github.com/example/interact.git", "main")),
    )
    monkeypatch.setattr(
        "pallas.console.cli.commands.community_plugin_cmd.install_community_plugin_with_options",
        AsyncMock(
            return_value={
                "plugin_id": "interact",
                "message": "已安装到 local/plugins/interact/。 已在当前进程直接加载。",
                "activation_action": "hot-reload",
            },
        ),
    )
    code = await community_plugin_cmd.run_install_async(
        "interact",
        repository_url="",
        ref="main",
        restart=False,
    )
    assert code == 0


@pytest.mark.asyncio
async def test_cli_update_uses_community_plugin_ops(monkeypatch) -> None:
    from pallas.console.cli.commands import community_plugin_cmd

    monkeypatch.setattr(
        "pallas.console.cli.commands.community_plugin_cmd.update_community_plugin_with_options",
        AsyncMock(
            return_value={
                "plugin_id": "interact",
                "message": "已更新 local/plugins/interact/。",
            },
        ),
    )
    code = await community_plugin_cmd.run_update_async("interact", ref="main", restart=False)
    assert code == 0
