from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.console.cli.update_ops import apply_bot_update


@pytest.mark.asyncio
async def test_apply_bot_update_with_restart(monkeypatch):
    monkeypatch.setattr(
        "src.plugins.pallas_webui.manager.apply_bot_repository_update",
        AsyncMock(return_value={"tag": "v4.0.0", "message": "仓库已更新。"}),
    )
    monkeypatch.setattr(
        "src.console.cli.bot_process.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.console.cli.bot_process.schedule_bot_restart",
        lambda **_: True,
    )
    monkeypatch.setattr(
        "src.console.cli.update_ops.webui_update_settings_from_repo",
        lambda: {"github_token": ""},
    )

    out = await apply_bot_update(restart=True)
    assert out["restart_scheduled"] is True
    assert "已安排" in str(out.get("message"))
