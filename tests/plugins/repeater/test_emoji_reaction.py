import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_sent_reactions_bounded():
    from packages.repeater.emoji_reaction import (
        SENT_REACTIONS_MAX_SIZE,
        mark_reaction_sent,
        sent_reactions,
    )

    bot_id = "test_bot_bound"
    try:
        for i in range(SENT_REACTIONS_MAX_SIZE + 5000):
            mark_reaction_sent(bot_id, i)

        assert len(sent_reactions[bot_id]) <= SENT_REACTIONS_MAX_SIZE
    finally:
        sent_reactions.pop(bot_id, None)


def test_sent_reactions_keeps_recent():
    from packages.repeater.emoji_reaction import (
        mark_reaction_sent,
        sent_reactions,
    )

    bot_id = "test_bot_recent"
    try:
        for i in range(15000):
            mark_reaction_sent(bot_id, i)

        remaining = sent_reactions[bot_id]
        timestamps = list(remaining.values())
        assert timestamps == sorted(timestamps)
    finally:
        sent_reactions.pop(bot_id, None)


@pytest.mark.asyncio
async def test_handle_auto_reaction_dispatches_background_send(monkeypatch):
    import packages.repeater.emoji_reaction as mod

    event = SimpleNamespace(
        message_id=123,
        group_id=456,
        likes=[{"emoji_id": 66}],
        self_id="10001",
    )
    bot = SimpleNamespace(self_id="10001")
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_send(_bot, _event, _emoji_code):
        started.set()
        await release.wait()

    task: asyncio.Task[None] | None = None
    original_create_task = asyncio.create_task

    def create_task(coro, *, name=None):
        nonlocal task
        task = original_create_task(coro, name=name)
        return task

    monkeypatch.setattr(
        mod,
        "plugin_config",
        SimpleNamespace(enable_auto_reply_on_reaction=True, reply_with_same_emoji=True),
    )
    monkeypatch.setattr(mod, "send_reaction", slow_send)
    monkeypatch.setattr(mod, "has_sent_reaction", lambda *_args: False)
    monkeypatch.setattr(mod.asyncio, "create_task", create_task)

    try:
        await asyncio.wait_for(mod.handle_auto_reaction(bot, event, {}), timeout=0.05)
        await asyncio.wait_for(started.wait(), timeout=0.05)
        assert task is not None
        assert task.done() is False
    finally:
        release.set()
        if task is not None:
            await task


@pytest.mark.asyncio
async def test_background_auto_reaction_send_swallows_timeout(monkeypatch):
    import packages.repeater.emoji_reaction as mod

    event = SimpleNamespace(message_id=123, group_id=456, self_id="10001")
    bot = SimpleNamespace(self_id="10001")

    monkeypatch.setattr(mod, "has_sent_reaction", lambda *_args: False)
    mark_reaction_sent = Mock()
    monkeypatch.setattr(mod, "mark_reaction_sent", mark_reaction_sent)

    async def slow_send(_bot, _event, _emoji_code):
        await asyncio.sleep(0.2)

    monkeypatch.setattr(mod, "send_reaction", slow_send)

    await mod.run_auto_reaction_send(bot, event, "66", timeout_s=0.01)

    mark_reaction_sent.assert_not_called()


def test_dispatch_auto_reaction_send_skips_when_too_many_pending(monkeypatch):
    import packages.repeater.emoji_reaction as mod

    bot = SimpleNamespace(self_id="10001")
    event = SimpleNamespace(message_id=123, group_id=456, self_id="10001")
    created: list[object] = []

    def create_task(coro, *, name=None):
        created.append((coro, name))
        return SimpleNamespace(add_done_callback=lambda _cb: None)

    monkeypatch.setattr(mod.asyncio, "create_task", create_task)
    monkeypatch.setattr(mod, "_auto_reaction_tasks", {object() for _ in range(mod.AUTO_REACTION_MAX_PENDING)})

    mod.dispatch_auto_reaction_send(bot, event, "66")

    assert created == []
