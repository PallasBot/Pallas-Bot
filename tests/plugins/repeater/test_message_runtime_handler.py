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
