from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _group_event(*, plain_text: str = "好耶", to_me: bool = False) -> MagicMock:
    event = MagicMock()
    event.self_id = 300
    event.group_id = 100
    event.user_id = 200
    event.message_id = 400
    event.message = []
    event.is_tome.return_value = to_me
    event.get_plaintext.return_value = plain_text
    event.raw_message = plain_text
    event.time = 123
    return event


@pytest.mark.asyncio
async def test_repeater_dispatches_locally_without_llm_select(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.handlers import message as mod
    from packages.repeater.responder import ReplyBundle

    event = _group_event(plain_text="草")
    bot = MagicMock()
    bot.self_id = "300"

    bundle = ReplyBundle(
        answer_list=["经典接话"],
        answer_keywords="测试",
        message_pool=["经典接话"],
        reply_mode="normal",
    )
    answers = ["经典接话"]
    dispatched: list[tuple[int, int, list[str]]] = []

    chat_instance = MagicMock()
    chat_instance.chat_data = SimpleNamespace(
        bot_id=300,
        group_id=100,
        raw_message="草",
        keywords="草",
        keywords_len=1,
        is_plain_text=True,
    )
    chat_instance.find_reply_bundle = AsyncMock(return_value=bundle)
    chat_instance.answer_from_bundle = AsyncMock(return_value=answers)
    monkeypatch.setattr(
        mod,
        "prepare_repeater_reply",
        AsyncMock(return_value=SimpleNamespace(bundle=bundle, fanout_gate=SimpleNamespace(lost=False, won=False))),
    )

    monkeypatch.setattr(
        mod,
        "build_repeater_event_context",
        AsyncMock(return_value=SimpleNamespace(plain_body="草", norm_raw="草", sharding_active=False)),
    )
    monkeypatch.setattr(mod, "is_message_scrub_blocked_async", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "enqueue_repeater_learn", AsyncMock())
    monkeypatch.setattr(mod, "Chat", MagicMock(return_value=chat_instance))
    monkeypatch.setattr(
        "packages.repeater.fanout_reply.dispatch_repeater_reply",
        lambda bot_id, group_id, payload: dispatched.append((bot_id, group_id, payload)),
    )
    monkeypatch.setattr(
        mod,
        "BotConfig",
        lambda *_args, **_kwargs: SimpleNamespace(refresh_cooldown=AsyncMock()),
    )
    await mod.handle_group_message(bot, event)

    chat_instance.answer_from_bundle.assert_awaited_once_with(bundle)
    assert dispatched == [(300, 100, answers)]


@pytest.mark.asyncio
async def test_message_handler_uses_reply_preparation_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.handlers import message as mod

    event = _group_event()
    bot = MagicMock()
    bot.self_id = "300"
    chat_instance = MagicMock()
    prepared = SimpleNamespace(bundle=None, fanout_gate=None)

    monkeypatch.setattr(
        mod,
        "build_repeater_event_context",
        AsyncMock(return_value=SimpleNamespace(plain_body="好耶", norm_raw="好耶", sharding_active=False)),
    )
    monkeypatch.setattr(mod, "is_message_scrub_blocked_async", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "Chat", MagicMock(return_value=chat_instance))
    monkeypatch.setattr(mod, "BotConfig", MagicMock())
    monkeypatch.setattr(mod, "prepare_repeater_reply", AsyncMock(return_value=prepared))
    learn = AsyncMock()
    monkeypatch.setattr(mod, "enqueue_repeater_learn", learn)

    await mod.handle_group_message(bot, event)

    mod.prepare_repeater_reply.assert_awaited_once_with(
        event,
        chat_instance,
        plain_body="好耶",
        sharding_active=False,
    )
    learn.assert_awaited_once_with(chat_instance, event)
