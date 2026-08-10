from __future__ import annotations

import asyncio

import pytest

from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext


def _context(*, is_to_me: bool = False) -> MessageContext:
    return MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="闲聊",
        raw_text="闲聊",
        is_to_me=is_to_me,
        command_traffic=False,
        route_modules=frozenset(),
    )


@pytest.mark.asyncio
async def test_repeater_native_handler_builds_deferred_and_remote_fanout_actions(monkeypatch) -> None:
    from packages.repeater.message_runtime_handler import build_repeater_fanout_outcome

    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.bot_has_cluster_connection",
        lambda bot_id: bot_id in {10, 20},
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.bot_has_local_connection",
        lambda bot_id: bot_id == 10,
    )
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)

    event = type(
        "Event",
        (),
        {
            "group_id": 2,
            "user_id": 3,
            "raw_message": "闲聊",
            "time": 4,
            "get_plaintext": lambda self: "闲聊",
        },
    )()
    bundle = type(
        "Bundle",
        (),
        {
            "answer_list": ["reply"],
            "answer_keywords": "key",
            "message_pool": ["reply"],
            "reply_mode": "normal",
            "reply_source": "same_group",
            "recent_hit": False,
            "repeat_hit": False,
            "pick_path": "default",
        },
    )()

    outcome = build_repeater_fanout_outcome(event, (10, 20), bundle)

    assert outcome.handled is True
    assert [action.name for action in outcome.deferred_actions] == ["repeater_fanout_10_2"]
    assert [(action.target_bot_id, action.payload["delay_sec"]) for action in outcome.cross_worker_actions] == [
        (20, 0.35)
    ]


def test_repeater_native_handler_builds_deferred_local_reply_action(monkeypatch) -> None:
    from packages.repeater.message_runtime_handler import build_repeater_local_reply_outcome

    scheduled: list[tuple[int, int, object]] = []

    async def dispatch(bot_id: int, group_id: int, answers: object) -> None:
        scheduled.append((bot_id, group_id, answers))

    monkeypatch.setattr("packages.repeater.fanout_reply._run_repeater_reply_send", dispatch)
    monkeypatch.setattr(
        "packages.repeater.fanout_reply.asyncio.create_task",
        lambda *_args, **_kwargs: pytest.fail("native deferred action must not schedule another task"),
    )
    answers = object()
    outcome = build_repeater_local_reply_outcome(10, 2, answers)

    assert outcome.handled is True
    assert [action.name for action in outcome.deferred_actions] == ["repeater_reply_10_2"]

    asyncio.run(outcome.deferred_actions[0].run())
    assert scheduled == [(10, 2, answers)]


@pytest.mark.asyncio
async def test_repeater_native_handler_handles_terminal_event_context_gate(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    def unexpected_llm_config():
        raise AssertionError("terminal event gate must not resolve LLM config")

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", unexpected_llm_config)
    monkeypatch.setattr("packages.repeater.event_gate.build_repeater_event_context", AsyncMock(return_value=None))

    outcome = await RepeaterNativeHandler().build_fanout_plan(
        _context(),
        bot=type("Bot", (), {"self_id": 10})(),
        event=object(),
    )

    assert outcome == HandlingOutcome(handled=True)


@pytest.mark.asyncio
async def test_repeater_native_handler_handles_local_reply_without_llm(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    handler = RepeaterNativeHandler()
    answers = object()
    bundle = object()
    chat = type("Chat", (), {"answer_from_bundle": AsyncMock(return_value=answers)})()
    event = type(
        "Event",
        (),
        {
            "self_id": 10,
            "group_id": 2,
            "message_id": 3,
            "message": [],
            "is_tome": lambda self: False,
        },
    )()
    refresh_cooldown = AsyncMock()
    learn = AsyncMock()

    async def build_context(_bot_id, _event):
        return type("Context", (), {"plain_body": "闲聊", "norm_raw": "闲聊", "sharding_active": False})()

    monkeypatch.setattr("packages.repeater.event_gate.build_repeater_event_context", build_context)
    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "packages.repeater.reply_preparation.prepare_repeater_reply",
        AsyncMock(return_value=type("Prepared", (), {"bundle": bundle, "fanout_gate": None})()),
    )
    monkeypatch.setattr("packages.repeater.model.Chat", lambda _event: chat)
    monkeypatch.setattr("packages.repeater.learn_queue.enqueue_repeater_learn", learn)
    monkeypatch.setattr(
        "pallas.core.foundation.config.BotConfig",
        lambda *_args: type("Config", (), {"refresh_cooldown": refresh_cooldown})(),
    )
    monkeypatch.setattr("pallas.core.platform.ingress.hotpath_metrics.record_reply_local_dispatched", lambda: None)

    outcome = await handler.build_fanout_plan(_context(), bot=type("Bot", (), {"self_id": 10})(), event=event)

    assert outcome.handled is True
    assert [action.name for action in outcome.deferred_actions] == [
        "repeater_capture_learn_10_2_3",
        "repeater_reply_10_2",
    ]
    chat.answer_from_bundle.assert_awaited_once_with(bundle)
    learn.assert_not_awaited()
    refresh_cooldown.assert_awaited_once_with("repeat")

    await outcome.deferred_actions[0].run()
    learn.assert_awaited_once_with(chat, event)


@pytest.mark.parametrize(
    ("is_to_me", "has_bundle", "fallback_reason"),
    [
        (True, True, "unexpected_to_me"),
    ],
)
@pytest.mark.asyncio
async def test_repeater_native_handler_labels_nonreply_fallbacks(
    monkeypatch,
    is_to_me: bool,
    has_bundle: bool,
    fallback_reason: str,
) -> None:
    from unittest.mock import AsyncMock

    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    event = type(
        "Event",
        (),
        {
            "self_id": 10,
            "group_id": 2,
            "message_id": 3,
            "message": [],
            "is_tome": lambda self: is_to_me,
        },
    )()

    async def build_context(_bot_id, _event):
        return type("Context", (), {"plain_body": "闲聊", "norm_raw": "闲聊", "sharding_active": False})()

    monkeypatch.setattr("packages.repeater.event_gate.build_repeater_event_context", build_context)
    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "packages.repeater.reply_preparation.prepare_repeater_reply",
        AsyncMock(
            return_value=type("Prepared", (), {"bundle": object() if has_bundle else None, "fanout_gate": None})()
        ),
    )
    monkeypatch.setattr("packages.repeater.model.Chat", lambda _event: object())

    outcome = await RepeaterNativeHandler().build_fanout_plan(
        _context(),
        bot=type("Bot", (), {"self_id": 10})(),
        event=event,
    )

    assert outcome == HandlingOutcome(
        handled=False,
        fallback_to_legacy=True,
        fallback_reason=fallback_reason,
    )


@pytest.mark.asyncio
async def test_repeater_native_handler_handles_no_reply_bundle_after_capture_and_learn(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    calls: list[str] = []
    chat = object()
    event = type(
        "Event",
        (),
        {
            "self_id": 10,
            "group_id": 2,
            "message_id": 3,
            "message": [type("Segment", (), {"type": "image"})()],
            "is_tome": lambda self: False,
        },
    )()

    async def build_context(_bot_id, _event):
        return type("Context", (), {"plain_body": "闲聊", "norm_raw": "闲聊", "sharding_active": False})()

    async def insert_image(*_args, **_kwargs):
        calls.append("image")

    async def enqueue_learn(*_args, **_kwargs):
        calls.append("learn")

    def unexpected_llm_config():
        raise AssertionError("no-reply bundle must not resolve LLM config")

    monkeypatch.setattr("packages.repeater.event_gate.build_repeater_event_context", build_context)
    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "packages.repeater.reply_preparation.prepare_repeater_reply",
        AsyncMock(return_value=type("Prepared", (), {"bundle": None, "fanout_gate": None})()),
    )
    monkeypatch.setattr("packages.repeater.model.Chat", lambda _event: chat)
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.insert_image", insert_image)
    monkeypatch.setattr("packages.repeater.learn_queue.enqueue_repeater_learn", enqueue_learn)
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", unexpected_llm_config)

    outcome = await RepeaterNativeHandler().build_fanout_plan(
        _context(),
        bot=type("Bot", (), {"self_id": 10})(),
        event=event,
    )

    assert outcome.handled is True
    assert outcome.fallback_to_legacy is False
    assert [action.name for action in outcome.deferred_actions] == ["repeater_capture_learn_10_2_3"]
    assert calls == []

    await outcome.deferred_actions[0].run()
    assert calls == ["image", "learn"]


@pytest.mark.asyncio
async def test_repeater_native_handler_fanout_skips_llm_config(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import packages.repeater.message_runtime_handler as module

    event = SimpleNamespace(
        self_id=10,
        group_id=2,
        message_id=3,
        message=[],
        is_tome=lambda: False,
    )
    bundle = object()

    async def build_context(_bot_id, _event):
        return SimpleNamespace(plain_body="闲聊", norm_raw="闲聊", sharding_active=False)

    def unexpected_llm_config():
        raise AssertionError("won fanout must not resolve LLM config")

    monkeypatch.setattr("packages.repeater.event_gate.build_repeater_event_context", build_context)
    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "packages.repeater.reply_preparation.prepare_repeater_reply",
        AsyncMock(
            return_value=SimpleNamespace(
                bundle=bundle,
                fanout_gate=SimpleNamespace(won=True, bot_ids=(10,)),
            )
        ),
    )
    monkeypatch.setattr("packages.repeater.model.Chat", lambda _event: object())
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", unexpected_llm_config)
    monkeypatch.setattr(module, "build_repeater_fanout_outcome", lambda *_args: HandlingOutcome(handled=True))

    outcome = await module.RepeaterNativeHandler().build_fanout_plan(
        _context(),
        bot=SimpleNamespace(self_id=10),
        event=event,
    )

    assert outcome.handled is True
    assert [action.name for action in outcome.deferred_actions] == ["repeater_capture_learn_10_2_3"]


@pytest.mark.asyncio
async def test_repeater_native_handler_dispatches_locally_when_llm_is_enabled(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    event = type(
        "Event",
        (),
        {
            "self_id": 10,
            "group_id": 2,
            "message_id": 3,
            "message": [],
            "is_tome": lambda self: False,
        },
    )()

    async def build_context(_bot_id, _event):
        return type("Context", (), {"plain_body": "闲聊", "norm_raw": "闲聊", "sharding_active": False})()

    monkeypatch.setattr("packages.repeater.event_gate.build_repeater_event_context", build_context)
    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", AsyncMock(return_value=False))
    bundle = object()
    answers = object()
    chat = type("Chat", (), {"answer_from_bundle": AsyncMock(return_value=answers)})()
    monkeypatch.setattr(
        "packages.repeater.reply_preparation.prepare_repeater_reply",
        AsyncMock(return_value=type("Prepared", (), {"bundle": bundle, "fanout_gate": None})()),
    )
    monkeypatch.setattr("packages.repeater.model.Chat", lambda _event: chat)
    refresh_cooldown = AsyncMock()
    monkeypatch.setattr(
        "pallas.core.foundation.config.BotConfig",
        lambda *_args: type("Config", (), {"refresh_cooldown": refresh_cooldown})(),
    )
    monkeypatch.setattr("pallas.core.platform.ingress.hotpath_metrics.record_reply_local_dispatched", lambda: None)

    outcome = await RepeaterNativeHandler().build_fanout_plan(
        _context(),
        bot=type("Bot", (), {"self_id": 10})(),
        event=event,
    )

    assert outcome.handled is True
    assert [action.name for action in outcome.deferred_actions] == [
        "repeater_capture_learn_10_2_3",
        "repeater_reply_10_2",
    ]
    chat.answer_from_bundle.assert_awaited_once_with(bundle)


@pytest.mark.asyncio
async def test_repeater_native_handler_keeps_learning_when_local_reply_has_no_answers(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    handler = RepeaterNativeHandler()
    bundle = object()
    chat = type("Chat", (), {"answer_from_bundle": AsyncMock(return_value=None)})()
    event = type(
        "Event",
        (),
        {
            "self_id": 10,
            "group_id": 2,
            "message_id": 3,
            "message": [],
            "is_tome": lambda self: False,
        },
    )()
    learn = AsyncMock()

    async def build_context(_bot_id, _event):
        return type("Context", (), {"plain_body": "闲聊", "norm_raw": "闲聊", "sharding_active": False})()

    monkeypatch.setattr("packages.repeater.event_gate.build_repeater_event_context", build_context)
    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "packages.repeater.reply_preparation.prepare_repeater_reply",
        AsyncMock(return_value=type("Prepared", (), {"bundle": bundle, "fanout_gate": None})()),
    )
    monkeypatch.setattr("packages.repeater.model.Chat", lambda _event: chat)
    monkeypatch.setattr("packages.repeater.learn_queue.enqueue_repeater_learn", learn)

    outcome = await handler.build_fanout_plan(_context(), bot=type("Bot", (), {"self_id": 10})(), event=event)

    assert outcome.handled is True
    assert [action.name for action in outcome.deferred_actions] == ["repeater_capture_learn_10_2_3"]
    learn.assert_not_awaited()

    await outcome.deferred_actions[0].run()
    learn.assert_awaited_once_with(chat, event)


@pytest.mark.asyncio
async def test_repeater_native_handler_keeps_to_me_traffic_for_legacy(monkeypatch) -> None:
    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    handler = RepeaterNativeHandler()
    expected = HandlingOutcome(handled=False, fallback_to_legacy=True)

    async def fallback_plan(_context, *, bot, event):
        return expected

    monkeypatch.setattr(handler, "build_fanout_plan", fallback_plan)

    assert await handler.handle(_context(is_to_me=True), bot="bot", event="event") == expected


@pytest.mark.asyncio
async def test_repeater_native_handler_uses_native_outcome_for_fanout(monkeypatch) -> None:
    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    handler = RepeaterNativeHandler()
    expected = HandlingOutcome(handled=True)

    async def fake_build_fanout_plan(_context, *, bot, event):
        assert bot == "bot"
        assert event == "event"
        return expected

    monkeypatch.setattr(handler, "build_fanout_plan", fake_build_fanout_plan)

    assert await handler.handle(_context(), bot="bot", event="event") is expected


@pytest.mark.asyncio
async def test_repeater_native_handler_keeps_legacy_execution_for_non_fanout(monkeypatch) -> None:
    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    handler = RepeaterNativeHandler()

    async def fallback_plan(_context, *, bot, event):
        return HandlingOutcome(handled=False, fallback_to_legacy=True)

    monkeypatch.setattr(handler, "build_fanout_plan", fallback_plan)

    outcome = await handler.handle(_context(), bot="bot", event="event")

    assert outcome == HandlingOutcome(handled=False, fallback_to_legacy=True)


def test_repeater_native_handler_does_not_compete_with_direct_llm_chat() -> None:
    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    assert RepeaterNativeHandler().accepts(_context(is_to_me=True)) is False
