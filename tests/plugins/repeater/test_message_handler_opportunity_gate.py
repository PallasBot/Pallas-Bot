from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from operator import itemgetter
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
    from packages.repeater.model import Chat
    from packages.repeater.responder import Responder
    from pallas.core.foundation.db import Answer, Context

    event = _group_event(plain_text="今天又炸了")
    bot = MagicMock()
    bot.self_id = "300"
    chat_data = SimpleNamespace(
        group_id=100,
        bot_id=300,
        raw_message="今天又炸了",
        plain_text="今天又炸了",
        keywords="今天 炸了",
        keywords_len=2,
        is_plain_text=True,
        is_image=False,
        to_me=False,
        _keywords_list=["今天", "炸了"],
    )
    config = SimpleNamespace(drunkenness=AsyncMock(return_value=0), refresh_cooldown=AsyncMock())
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    context = Context.model_construct(
        keywords="今天 炸了",
        time=1,
        trigger_count=1,
        answers=[
            Answer(keywords="候选一", group_id=100, count=100, time=1, messages=["经典接话"]),
            Answer(keywords="候选二", group_id=100, count=100, time=1, messages=["另一条真实语料"]),
        ],
        ban=[],
        clear_time=0,
    )
    persona = SimpleNamespace(
        reply_bias=1.0,
        speak_bias=1.0,
        chaos_bias=0.0,
        warmth=0.0,
        assertiveness=0.0,
        bluntness=0.0,
        harsh_msg_ratio=0.0,
        polite_msg_ratio=0.0,
        tone="neutral",
        length_pref="any",
    )
    monkeypatch.setattr("packages.repeater.responder.pg_pool_under_pressure", lambda **_kwargs: False)
    monkeypatch.setattr(
        "packages.repeater.responder.context_repo.find_by_keywords_for_reply",
        AsyncMock(return_value=context),
    )
    monkeypatch.setattr("packages.repeater.responder.BanManager.find_ban_keywords", AsyncMock(return_value=set()))
    monkeypatch.setattr("pallas.product.persona.resolve_persona_for_message", AsyncMock(return_value=persona))
    monkeypatch.setattr("pallas.product.persona.loader.load_affect_triggers", AsyncMock(return_value=[]))
    monkeypatch.setattr("packages.repeater.activity_gate.group_has_hosted_activity", lambda _group_id: False)
    monkeypatch.setattr("packages.repeater.responder.load_feedback_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "packages.repeater.responder.random.choices",
        lambda population, *_args, **_kwargs: [population[-1]],
    )
    monkeypatch.setattr("packages.repeater.responder.random.choice", itemgetter(0))
    monkeypatch.setattr("packages.repeater.responder.random.random", lambda: 0.999999)

    bundle = await Responder.find_reply_bundle(chat_data, config, reply_dict, message_dict, recent_topics)

    assert bundle is not None
    assert bundle.message_pool == ["经典接话", "另一条真实语料"]
    assert bundle.answer_list == ["另一条真实语料"]

    monkeypatch.setattr(Chat, "_reply_dict", reply_dict)
    monkeypatch.setattr(Chat, "_recent_topics", recent_topics)
    monkeypatch.setattr(Chat, "_reply_lock", asyncio.Lock())
    monkeypatch.setattr(Chat, "_topics_lock", asyncio.Lock())
    chat_instance = Chat.__new__(Chat)
    chat_instance.chat_data = chat_data
    chat_instance.config = config
    dispatched: list[tuple[int, int, object]] = []
    monkeypatch.setattr(
        mod,
        "prepare_repeater_reply",
        AsyncMock(return_value=SimpleNamespace(bundle=bundle, fanout_gate=SimpleNamespace(lost=False, won=False))),
    )

    monkeypatch.setattr(
        mod,
        "build_repeater_event_context",
        AsyncMock(return_value=SimpleNamespace(plain_body="今天又炸了", norm_raw="今天又炸了", sharding_active=False)),
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
        lambda *_args, **_kwargs: config,
    )
    await mod.handle_group_message(bot, event)

    assert len(dispatched) == 1
    dispatched_bot_id, dispatched_group_id, answers = dispatched[0]
    assert (dispatched_bot_id, dispatched_group_id) == (300, 100)
    assert [str(message) async for message in answers] == ["另一条真实语料"]


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
