from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_greeting_ignores_group_msg_emoji_like(monkeypatch) -> None:
    import src.plugins.greeting as mod

    monkeypatch.setattr(mod, "greeting_plugin_disabled", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        mod,
        "get_bot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not call get_bot")),
    )

    event = SimpleNamespace(
        notice_type="group_msg_emoji_like",
        sub_type="",
        self_id="123456",
        group_id=654321,
        target_id=0,
        user_id=0,
    )

    await mod.handle_notice(event)
