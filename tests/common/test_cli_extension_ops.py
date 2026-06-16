from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.console.cli.extension_ops import append_restart_note


def test_append_restart_note_scheduled():
    assert "已安排" in append_restart_note("安装完成", scheduled=True)


@pytest.mark.asyncio
async def test_install_with_restart_schedules(monkeypatch):
    from src.console.cli import extension_ops

    monkeypatch.setattr(extension_ops, "bot_lifecycle_available", lambda: True)
    monkeypatch.setattr(extension_ops, "schedule_bot_restart", lambda **_: True)
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
    assert "已安排" in str(out.get("message"))
