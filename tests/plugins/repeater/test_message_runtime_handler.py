from __future__ import annotations

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


@pytest.mark.asyncio
async def test_repeater_native_handler_does_not_run_side_effects_before_legacy_fallback(monkeypatch) -> None:
    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    handler = RepeaterNativeHandler()
    calls: list[str] = []
    event = type(
        "Event",
        (),
        {
            "self_id": 1,
            "group_id": 2,
            "message_id": 3,
            "message": [type("Segment", (), {"type": "image"})()],
            "is_tome": lambda self: False,
        },
    )()

    async def build_context(_bot_id, _event):
        return type("Context", (), {"plain_body": "闲聊", "norm_raw": "闲聊", "sharding_active": False})()

    async def not_scrubbed(**_kwargs):
        return False

    async def prepare(_event, _chat, **_kwargs):
        return type("Prepared", (), {"bundle": object(), "fanout_gate": None})()

    def chat(_event):
        return object()

    async def insert_image(*_args, **_kwargs):
        calls.append("image")

    async def enqueue_learn(*_args, **_kwargs):
        calls.append("learn")

    monkeypatch.setattr("packages.repeater.event_gate.build_repeater_event_context", build_context)
    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", not_scrubbed)
    monkeypatch.setattr("packages.repeater.reply_preparation.prepare_repeater_reply", prepare)
    monkeypatch.setattr("packages.repeater.model.Chat", chat)
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.insert_image", insert_image)
    monkeypatch.setattr("packages.repeater.learn_queue.enqueue_repeater_learn", enqueue_learn)

    outcome = await handler.build_fanout_plan(_context(), bot=type("Bot", (), {"self_id": 1})(), event=event)

    assert outcome == HandlingOutcome(handled=False, fallback_to_legacy=True)
    assert calls == []


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
