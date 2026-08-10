from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from packages.pb_webui.manager import BotGitUpdateError
from pallas.console.cli import update_ops
from pallas.console.cli.update_ops import apply_bot_update


@pytest.mark.asyncio
async def test_apply_bot_update_with_restart(monkeypatch):
    monkeypatch.setattr(
        "packages.pb_webui.manager.apply_bot_repository_update",
        AsyncMock(return_value={"tag": "v4.0.0", "message": "仓库已更新。"}),
    )
    monkeypatch.setattr(
        "pallas.console.cli.bot_process.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.bot_process.schedule_bot_restart",
        lambda **_: True,
    )
    monkeypatch.setattr(
        "pallas.console.cli.update_ops.webui_update_settings_from_repo",
        lambda: {"github_token": ""},
    )

    out = await apply_bot_update(restart=True)
    assert out["restart_scheduled"] is True
    assert "已安排" in str(out.get("message"))


@pytest.mark.asyncio
async def test_apply_bot_update_uses_release_bundle_in_docker(monkeypatch, tmp_path):
    install = AsyncMock(return_value={"tag": "v4.2.0", "applied_file_count": 12})
    sync = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "packages.pb_webui.manager.inspect_bot_deployment",
        lambda: {"deployment_mode": "docker", "git_available": False},
    )
    monkeypatch.setattr(
        "packages.pb_webui.manager.fetch_latest_bot_release",
        AsyncMock(return_value={"tag": "v4.2.0"}),
    )
    monkeypatch.setattr("packages.pb_webui.bot_release_bundle.install_docker_release_bundle", install)
    monkeypatch.setattr(update_ops, "sync_docker_release_dependencies", sync)
    monkeypatch.setattr(update_ops, "write_runtime_overlay_version", lambda tag: None)
    monkeypatch.setattr(update_ops, "pallas_bot_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        "pallas.console.cli.update_ops.webui_update_settings_from_repo",
        lambda: {"github_token": ""},
    )

    out = await apply_bot_update(track="release")

    assert out["tag"] == "v4.2.0"
    install.assert_awaited_once()
    sync.assert_awaited_once_with(tmp_path, on_progress=None)


@pytest.mark.asyncio
async def test_apply_bot_update_rejects_branch_track_in_docker(monkeypatch):
    monkeypatch.setattr(
        "packages.pb_webui.manager.inspect_bot_deployment",
        lambda: {"deployment_mode": "docker", "git_available": False},
    )
    monkeypatch.setattr(
        "pallas.console.cli.update_ops.webui_update_settings_from_repo",
        lambda: {"github_token": ""},
    )

    with pytest.raises(BotGitUpdateError, match="Docker.*Release"):
        await apply_bot_update(track="branch")
