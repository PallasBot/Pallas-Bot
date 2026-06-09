from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_bot_status_ignores_group_msg_emoji_like(monkeypatch) -> None:
    import src.plugins.bot_status as mod

    called = False

    async def notify_bot_offline(*_args, **_kwargs) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(mod, "notify_bot_offline", notify_bot_offline)

    event = SimpleNamespace(
        notice_type="group_msg_emoji_like",
        sub_type="",
        user_id=123456,
        self_id="123456",
    )

    await mod.handle_bot_offline_events(event)

    assert called is False
