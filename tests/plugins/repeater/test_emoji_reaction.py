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


@pytest.mark.asyncio
async def test_send_reaction_uses_native_api_for_snowluma(monkeypatch):
    import packages.repeater.emoji_reaction as mod

    event = SimpleNamespace(message_id=99, group_id=1, self_id="10001")
    calls: list[tuple] = []

    async def call_api(name, **kwargs):
        calls.append((name, kwargs))

    async def get_version_info():
        return {"app_name": "SnowLuma"}

    bot = SimpleNamespace(self_id="10001", call_api=call_api, get_version_info=get_version_info)
    uniseg_called = {"n": 0}

    async def boom(*_a, **_k):
        uniseg_called["n"] += 1
        raise AssertionError("uniseg should not be used for SnowLuma")

    monkeypatch.setattr(mod, "has_sent_reaction", lambda *_a: False)
    monkeypatch.setattr(mod, "mark_reaction_sent", lambda *_a: None)
    monkeypatch.setattr(mod, "_maybe_feedback_emoji_fit", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "message_reaction", boom)

    await mod.send_reaction(bot, event, "66")

    assert uniseg_called["n"] == 0
    assert calls == [("set_msg_emoji_like", {"message_id": 99, "emoji_id": "66", "set": True})]


@pytest.mark.asyncio
async def test_send_reaction_logs_successful_reaction_at_info(monkeypatch):
    import packages.repeater.emoji_reaction as mod

    event = SimpleNamespace(message_id=99, group_id=1, self_id="10001")
    bot = SimpleNamespace(self_id="10001")
    info_logs: list[str] = []

    async def send_native(*_args, **_kwargs):
        return None

    async def app_name(_bot):
        return "SnowLuma"

    monkeypatch.setattr(mod, "send_msg_emoji_like", send_native)
    monkeypatch.setattr(mod, "onebot_app_name", app_name)
    monkeypatch.setattr(mod, "_maybe_feedback_emoji_fit", lambda *_a, **_k: None)
    monkeypatch.setattr(mod.logger, "info", info_logs.append)

    try:
        await mod.send_reaction(bot, event, "66")
    finally:
        mod.sent_reactions.pop("10001", None)

    assert info_logs == ["[Reaction] Bot [10001] reacted to message [99] in group [1] with [66]."]


@pytest.mark.asyncio
async def test_send_reaction_reserves_message_before_awaiting_protocol(monkeypatch):
    import packages.repeater.emoji_reaction as mod

    bot_id = "test_bot_concurrent"
    event = SimpleNamespace(message_id=99, group_id=1, self_id=bot_id)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def send_native(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()

    async def app_name(_bot):
        return "SnowLuma"

    bot = SimpleNamespace(self_id=bot_id)
    monkeypatch.setattr(mod, "send_msg_emoji_like", send_native)
    monkeypatch.setattr(mod, "onebot_app_name", app_name)
    monkeypatch.setattr(mod, "_maybe_feedback_emoji_fit", lambda *_a, **_k: None)

    first = asyncio.create_task(mod.send_reaction(bot, event, "66"))
    second: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(started.wait(), timeout=0.1)
        second = asyncio.create_task(mod.send_reaction(bot, event, "66"))
        await asyncio.sleep(0)
        assert calls == 1
    finally:
        release.set()
        await first
        if second is not None:
            second.cancel()
            await asyncio.gather(second, return_exceptions=True)
        mod.sent_reactions.pop(bot_id, None)


@pytest.mark.asyncio
async def test_send_reaction_releases_reservation_when_cancelled(monkeypatch):
    import packages.repeater.emoji_reaction as mod

    bot_id = "test_bot_cancelled"
    event = SimpleNamespace(message_id=99, group_id=1, self_id=bot_id)
    started = asyncio.Event()

    async def send_native(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    async def app_name(_bot):
        return "SnowLuma"

    bot = SimpleNamespace(self_id=bot_id)
    monkeypatch.setattr(mod, "send_msg_emoji_like", send_native)
    monkeypatch.setattr(mod, "onebot_app_name", app_name)

    task = asyncio.create_task(mod.send_reaction(bot, event, "66"))
    try:
        await asyncio.wait_for(started.wait(), timeout=0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert mod.has_sent_reaction(bot_id, 99) is False
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        mod.sent_reactions.pop(bot_id, None)
