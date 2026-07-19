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
async def test_opportunity_gate_only_skips_llm_enhancement(monkeypatch: pytest.MonkeyPatch) -> None:
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
    chat_instance.chat_data = SimpleNamespace(group_id=100, keywords_len=1, is_plain_text=True)
    chat_instance.find_reply_bundle = AsyncMock(return_value=bundle)
    chat_instance.answer_from_bundle = AsyncMock(return_value=answers)

    monkeypatch.setattr(
        mod,
        "build_repeater_event_context",
        AsyncMock(return_value=SimpleNamespace(plain_body="草", norm_raw="草", sharding_active=False)),
    )
    monkeypatch.setattr(mod, "is_message_scrub_blocked_async", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "enqueue_repeater_learn", AsyncMock())
    monkeypatch.setattr(mod, "Chat", MagicMock(return_value=chat_instance))
    monkeypatch.setattr(mod, "should_prepare_repeater_reply", lambda *args, **kwargs: True)
    monkeypatch.setattr(mod, "should_attempt_repeater_opportunity", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "maybe_submit_repeater_corpus_llm", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "maybe_submit_repeater_llm_fallback", AsyncMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "build_repeater_llm_plan",
        lambda *args, **kwargs: SimpleNamespace(
            stage_names=["select"],
            candidate_pool=["经典接话"],
            candidate_text="经典接话",
        ),
    )
    monkeypatch.setattr(mod, "run_repeater_llm_plan", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: SimpleNamespace(
            llm_chat_enabled=True,
            llm_select_enabled=True,
            llm_polish_enabled=True,
            llm_polish_lite_enabled=False,
        ),
    )
    monkeypatch.setattr(
        "packages.repeater.message_store.MessageStore._message_dict",
        {100: [SimpleNamespace(user_id=200), SimpleNamespace(user_id=201)]},
        raising=False,
    )
    monkeypatch.setattr(
        "packages.repeater.fanout_reply.repeater_can_attempt_reply",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "packages.repeater.fanout_reply.resolve_fanout_gate",
        AsyncMock(return_value=SimpleNamespace(lost=False, won=False, bot_ids=[])),
    )
    monkeypatch.setattr(
        "packages.repeater.fanout_reply.dispatch_repeater_reply",
        lambda bot_id, group_id, payload: dispatched.append((bot_id, group_id, payload)),
    )
    monkeypatch.setattr(mod, "record_bot_llm_route", lambda *args, **kwargs: None)
    from pallas.product.llm.kernel.models import ConversationFeatureLevel

    monkeypatch.setattr(
        mod,
        "resolve_conversation_feature_level",
        lambda _cfg: ConversationFeatureLevel.FULL_CONVERSATION_KERNEL,
    )
    monkeypatch.setattr(
        mod,
        "classify_behavior_scene",
        lambda *args, **kwargs: type("S", (), {"value": "smalltalk"})(),
    )
    trace_rows: list[dict[str, object]] = []
    monkeypatch.setattr(mod, "append_conversation_decision_trace", lambda row: trace_rows.append(dict(row)) or True)
    monkeypatch.setattr(
        mod,
        "BotConfig",
        lambda *_args, **_kwargs: SimpleNamespace(refresh_cooldown=AsyncMock()),
    )
    monkeypatch.setattr(mod, "SlowPathTimer", MagicMock())

    await mod.handle_group_message(bot, event)

    mod.run_repeater_llm_plan.assert_not_awaited()
    mod.maybe_submit_repeater_corpus_llm.assert_not_awaited()
    mod.maybe_submit_repeater_llm_fallback.assert_not_awaited()
    chat_instance.answer_from_bundle.assert_awaited_once_with(bundle)
    assert dispatched == [(300, 100, answers)]
    assert trace_rows
    assert trace_rows[0]["kind"] == "conversation_decision_trace"
    assert trace_rows[0]["opportunity_accepted"] is False
