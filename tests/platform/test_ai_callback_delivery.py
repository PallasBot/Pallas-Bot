from __future__ import annotations

from types import SimpleNamespace

import pytest
from nonebot.adapters.onebot.v11 import Message

from pallas.core.platform.ai_callback import task_types
from pallas.core.platform.ai_callback.delivery import build_group_text_message
from pallas.product.llm import delivery as llm_delivery
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.repeater_feedback import is_feedback_task_type


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"message_id": 12}, 12),
        (SimpleNamespace(message_id="13"), 13),
        ({"data": {"message_id": 14}}, 14),
        (SimpleNamespace(data=SimpleNamespace(message_id="15")), 15),
        ({"message_id": 0}, None),
        ({"message_id": "bad"}, None),
        ("not-a-receipt", None),
    ],
)
def test_parse_delivery_message_id(value, expected) -> None:
    from pallas.core.platform.ai_callback.delivery import parse_delivery_message_id

    assert parse_delivery_message_id(value) == expected


def test_retired_repeater_callback_task_types_are_not_public() -> None:
    for name in (
        "REPEATER_FALLBACK_TASK_TYPE",
        "REPEATER_POLISH_TASK_TYPE",
        "REPEATER_POLISH_LITE_TASK_TYPE",
        "REPEATER_SELECT_TASK_TYPE",
        "REPEATER_LLM_TASK_TYPES",
    ):
        assert not hasattr(task_types, name)


def test_delivery_tracks_and_collects_feedback_for_llm_chat_only() -> None:
    assert llm_delivery._TRACKED_LLM_TASKS == frozenset({"llm_chat"})
    assert is_feedback_task_type("llm_chat") is True
    assert is_feedback_task_type("repeater_fallback") is False
    assert is_feedback_task_type("repeater_polish") is False
    assert is_feedback_task_type("repeater_polish_lite") is False
    assert is_feedback_task_type("repeater_select") is False


@pytest.mark.parametrize(
    ("segments", "message_id", "delivered", "expected"),
    [
        (["没救了"], 123, True, True),
        (["没救啦"], 123, True, False),
        (["没", "救了"], 123, True, False),
        (["没救了"], None, True, False),
        (["没救了"], 123, False, False),
    ],
)
def test_semantic_source_binding_uses_final_delivery_segments(segments, message_id, delivered, expected) -> None:
    assert (
        llm_delivery.semantic_source_matches_delivery(
            {"semantic_style_direct_candidate": "没救了"},
            reply_segments=segments,
            bot_message_id=message_id,
            text_delivered=delivered,
        )
        is expected
    )


def test_build_group_text_message_keeps_plain_text_plain() -> None:
    message = build_group_text_message("收到")

    assert message == "收到"


def test_build_group_text_message_can_quote_or_mention_a_member() -> None:
    quoted = build_group_text_message("收到", reply_to_message_id=123)
    mentioned = build_group_text_message("收到", at_user_id=456)

    assert isinstance(quoted, Message)
    assert quoted[0].type == "reply"
    assert quoted[0].data["id"] == "123"
    assert mentioned[0].type == "at"
    assert mentioned[0].data["qq"] == "456"


@pytest.mark.asyncio
async def test_llm_callback_delivers_json_reply_segments_in_order_with_first_decoration(monkeypatch) -> None:
    sent: list[tuple[str, dict]] = []
    delays: list[float] = []

    async def fake_send_with_receipt(_bot, _group_id, text, **_kwargs):
        sent.append((text, _kwargs))
        return SimpleNamespace(message_id=len(sent), delivered=True)

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(llm_delivery, "send_group_message_with_receipt", fake_send_with_receipt, raising=False)
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        fake_send_with_receipt,
    )
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: False)
    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: LlmConfig(llm_reply_postprocess_enabled=False))

    reply_text, delivered, _ = await llm_delivery.deliver_llm_callback_success(
        "task-json-segments",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "reply_delivery_style": "QUOTE",
            "message_id": 88,
        },
        bot=SimpleNamespace(self_id="99"),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text='{"reply_segments":["先这样吧","回头再说"]}',
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=fake_sleep,
    )

    assert reply_text == "先这样吧\n回头再说"
    assert delivered is True
    assert sent == [
        ("先这样吧", {"reply_to_message_id": 88, "at_user_id": None}),
        ("回头再说", {"reply_to_message_id": None, "at_user_id": None}),
    ]
    assert delays == [llm_delivery.bubble_delay_seconds("先这样吧")]


@pytest.mark.asyncio
async def test_llm_callback_stops_after_a_failed_bubble(monkeypatch) -> None:
    sent: list[str] = []

    async def fake_send_with_receipt(_bot, _group_id, text, **_kwargs):
        sent.append(text)
        return SimpleNamespace(message_id=len(sent), delivered=len(sent) != 2)

    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        fake_send_with_receipt,
    )
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: False)

    async def fake_sleep(_delay: float) -> None:
        return None

    _reply_text, delivered, _ = await llm_delivery.deliver_llm_callback_success(
        "task-bubble-failure",
        {"task_type": "llm_chat", "bot_id": 99, "group_id": 42, "user_id": 7},
        bot=SimpleNamespace(self_id="99"),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text='{"reply_segments":["第一条","第二条","第三条"]}',
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=fake_sleep,
    )

    assert delivered is False
    assert sent == ["第一条", "第二条"]


@pytest.mark.asyncio
async def test_non_chat_callback_keeps_json_text_literal(monkeypatch) -> None:
    sent: list[str] = []

    async def fake_send_with_receipt(_bot, _group_id, text, **_kwargs):
        sent.append(text)
        return SimpleNamespace(message_id=1, delivered=True)

    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        fake_send_with_receipt,
    )
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: False)
    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: LlmConfig(llm_reply_postprocess_enabled=False))

    raw = '{"asset":"{keep this literal}"}'
    reply_text, delivered, _ = await llm_delivery.deliver_llm_callback_success(
        "task-draw-json",
        {"task_type": "draw_image", "bot_id": 99, "group_id": 42, "user_id": 7},
        bot=SimpleNamespace(self_id="99"),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text=raw,
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
    )

    assert reply_text == raw
    assert delivered is True
    assert sent == [raw]


@pytest.mark.asyncio
async def test_direct_candidate_bypasses_structured_parser(monkeypatch) -> None:
    sent: list[str] = []

    async def fake_send_with_receipt(_bot, _group_id, text, **_kwargs):
        sent.append(text)
        return SimpleNamespace(message_id=1, delivered=True)

    def parser_must_not_run(_raw: str):
        raise AssertionError("direct candidate must bypass structured parser")

    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        fake_send_with_receipt,
    )
    monkeypatch.setattr("pallas.product.llm.structured_reply.parse_structured_reply", parser_must_not_run)
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: False)
    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: LlmConfig(llm_reply_postprocess_enabled=False))

    reply_text, delivered, _ = await llm_delivery.deliver_llm_callback_success(
        "task-direct",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "semantic_style_direct_candidate": "第一句。\n第二句。",
        },
        bot=SimpleNamespace(self_id="99"),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="第一句。\n第二句。",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
    )

    assert reply_text == "第一句。\n第二句。"
    assert delivered is True
    assert sent == ["第一句。\n第二句。"]


def test_llm_mention_delivery_requires_multi_party_and_respects_group_cooldown(monkeypatch) -> None:
    monkeypatch.setattr(llm_delivery, "_MENTION_LAST_SENT_AT", {})
    task = {
        "task_type": "llm_chat",
        "reply_delivery_style": "MENTION",
        "has_multi_party_overlap": True,
        "user_id": 456,
    }

    assert llm_delivery.resolve_llm_reply_delivery(
        task,
        group_id=123,
        mention_cooldown_sec=900,
        now=1000,
    ) == (None, 456)
    llm_delivery.note_llm_reply_mention_sent(123, now=1000)
    assert llm_delivery.resolve_llm_reply_delivery(
        task,
        group_id=123,
        mention_cooldown_sec=900,
        now=1001,
    ) == (None, None)
    assert llm_delivery.resolve_llm_reply_delivery(
        {**task, "has_multi_party_overlap": False},
        group_id=123,
        mention_cooldown_sec=900,
        now=2000,
    ) == (None, None)
