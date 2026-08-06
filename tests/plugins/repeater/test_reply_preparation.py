from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_prepare_repeater_reply_skips_bundle_lookup_after_lost_fanout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.repeater import reply_preparation as mod

    event = MagicMock()
    event.self_id = 300
    event.group_id = 100
    chat = MagicMock()
    chat.find_reply_bundle = AsyncMock()
    lost_gate = SimpleNamespace(lost=True, won=False, bot_ids=())

    monkeypatch.setattr(mod, "repeater_can_attempt_reply", AsyncMock(return_value=True))
    monkeypatch.setattr(mod, "should_prepare_repeater_reply", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(mod, "resolve_fanout_gate", AsyncMock(return_value=lost_gate))

    result = await mod.prepare_repeater_reply(
        event,
        chat,
        plain_body="好耶",
        sharding_active=False,
    )

    assert result.bundle is None
    assert result.fanout_gate is lost_gate
    chat.find_reply_bundle.assert_not_awaited()
