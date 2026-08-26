from __future__ import annotations

import asyncio
from types import SimpleNamespace

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter
from nonebot.adapters.onebot.v11.event import GroupMessageEvent

from pallas.product.llm.event_observation import record_provider_prompt_hit
from pallas.product.llm.persona_context import llm_chat_prompt_override
from tools.llm_event_harness import (
    EventFixture,
    build_group_message_payload,
    initialize_event_runtime,
    run_event_case,
)


@pytest.fixture
def real_adapter() -> Adapter:
    return Adapter(nonebot.get_driver())


def _convert_to_event(payload: dict) -> GroupMessageEvent:
    runtime = asyncio.run(initialize_event_runtime())
    return runtime.adapter.json_to_event(payload)


def test_group_payload_converts_structural_fields_through_real_adapter() -> None:
    payload = build_group_message_payload(
        text="hello",
        images=[],
        to_me=True,
        bot_id="10001",
        group_id="20002",
        user_id="30003",
        message_id="9",
        sender_nickname="昵称",
        sender_role="admin",
    )

    event = _convert_to_event(payload)

    assert isinstance(event, GroupMessageEvent)
    assert event.group_id == 20002
    assert event.user_id == 30003
    assert event.self_id == 10001
    assert event.sender.nickname == "昵称"
    assert event.sender.role == "admin"
    assert event.to_me is False  # set by the Bot preprocessor, not json_to_event
    assert event.message[0].type == "at"
    assert str(event.message[0].data.get("qq")) == "10001"


def test_group_payload_without_at_has_no_at_segment() -> None:
    payload = build_group_message_payload(
        text="hello",
        images=[],
        to_me=False,
        bot_id="10001",
        group_id="20002",
        user_id="30003",
        message_id="9",
        sender_nickname="昵称",
        sender_role="member",
    )

    event = _convert_to_event(payload)

    assert isinstance(event, GroupMessageEvent)
    assert event.message[0].type == "text"
    assert all(seg.type != "at" for seg in event.message)


def test_run_event_case_delivers_with_context_forwarded_to_background_task() -> None:
    payload = build_group_message_payload(
        text="hello",
        images=[],
        to_me=True,
        bot_id="10001",
        group_id="20002",
        user_id="30003",
        message_id="9",
        sender_nickname="昵称",
        sender_role="member",
    )
    fixture = EventFixture(name="chain-case", event=payload)

    async def dispatch(bot, event):
        async def llm_turn():
            assert llm_chat_prompt_override.get() == "variant-prompt"
            record_provider_prompt_hit([
                {"role": "system", "content": "hello system"},
                {"role": "user", "content": "hi"},
            ])
            await bot.call_api("send_group_msg", message="reply-text", group_id=event.group_id)

        asyncio.create_task(llm_turn(), name="chain-llm-turn")
        return None

    runtime = SimpleNamespace(adapter=Adapter(nonebot.get_driver()), dispatch=dispatch)

    result = asyncio.run(
        run_event_case(
            fixture,
            prompt="variant-prompt",
            provider="aliyun",
            model="qwen3.7-max",
            temperature=0.7,
            variant="A",
            runtime=runtime,
        )
    )

    assert result.status == "delivered"
    assert result.reply == "reply-text"
    assert result.api_calls == [{"action": "send_group_msg", "params": {"message": "reply-text", "group_id": 20002}}]
    assert result.prompt_hits == ["hello system"]
    assert any(entry.get("stage") == "delivery" for entry in result.stages)
