from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm import delivery as llm_delivery
from pallas.product.llm.chat_empty_fallback import LLM_CHAT_EMPTY_FALLBACK
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.turn_telemetry import build_turn_event


def _capture_events(events: list[dict[str, object]]):
    def capture(**fields: object) -> None:
        events.append(build_turn_event(hash_key=b"delivery-test-key", **fields))

    return capture


def _task() -> dict[str, object]:
    return {
        "turn_id": "turn-delivery",
        "task_type": "llm_chat",
        "bot_id": 99,
        "group_id": 42,
        "user_id": 7,
    }


@pytest.mark.asyncio
async def test_delivery_emits_silent_output_and_delivery_events_without_reply_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(llm_delivery, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: False)
    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: LlmConfig(llm_reply_postprocess_enabled=False))

    result = await llm_delivery.deliver_llm_callback_success(
        "request-delivery-silent",
        _task(),
        bot=SimpleNamespace(self_id="99"),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        suppress_empty_fallback=True,
    )

    assert result.reply_text == ""
    assert result.text_delivered is False
    assert result.delivered is False
    assert result.status == "silent"
    output = next(event for event in events if event["stage"] == "output")
    delivery = next(event for event in events if event["stage"] == "delivery")
    assert output["output_filter_action"] == "silent"
    assert delivery["delivery_status"] == "silent"
    assert delivery["sent_bubble_count"] == 0
    assert delivery["total_bubble_count"] == 0
    assert "reply_text" not in output
    assert "text" not in output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("delivered_flags", "expected_status", "expected_delivered"),
    [
        ([True, True, True], "sent", True),
        ([False], "failed", False),
        ([True, False], "partial", False),
    ],
)
async def test_delivery_emits_status_for_complete_and_partial_bubbles(
    monkeypatch: pytest.MonkeyPatch,
    delivered_flags: list[bool],
    expected_status: str,
    expected_delivered: bool,
) -> None:
    events: list[dict[str, object]] = []
    sent: list[str] = []
    monkeypatch.setattr(llm_delivery, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: False)
    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: LlmConfig(llm_reply_postprocess_enabled=False))

    async def fake_send(_bot, _group_id, text, **_kwargs):
        index = len(sent)
        sent.append(str(text))
        return SimpleNamespace(message_id=index + 1, delivered=delivered_flags[index])

    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        fake_send,
    )

    result = await llm_delivery.deliver_llm_callback_success(
        "request-delivery-status",
        _task(),
        bot=SimpleNamespace(self_id="99"),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text='{"reply_segments":["第一条","第二条","第三条"]}',
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    delivery = next(event for event in events if event["stage"] == "delivery")
    assert result[2] is expected_delivered
    assert delivery["delivery_status"] == expected_status
    assert delivery["sent_bubble_count"] == sum(delivered_flags[: len(sent)])
    assert delivery["total_bubble_count"] == 3
    assert delivery["sent_message_id_hashes"]
    assert all("第一条" not in str(event) for event in events)


@pytest.mark.asyncio
async def test_query_tool_empty_model_reply_gets_visible_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, object]] = []
    sent: list[str] = []
    monkeypatch.setattr(llm_delivery, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: False)
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(
            llm_reply_postprocess_enabled=False,
            llm_reply_trim_terminal_period_enabled=False,
        ),
    )

    async def fake_send(_bot, _group_id, text, **_kwargs):
        sent.append(str(text))
        return SimpleNamespace(message_id=1, delivered=True)

    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        fake_send,
    )
    task = {
        **_task(),
        "speak_trigger": "to_me",
        "agent_trace": {
            "successful_query_call_count": 1,
            "query_tool_hit_count": 1,
        },
    }

    result = await llm_delivery.deliver_llm_callback_success(
        "request-query-fallback",
        task,
        bot=SimpleNamespace(self_id="99"),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="PASS",
        parsed_agent_trace=task["agent_trace"],
        history_summary=None,
        history_keep_messages=None,
        suppress_empty_fallback=True,
    )

    assert result.delivered is True
    assert sent == ["资料查到了，但这次回答没整理出来，再问我一次吧。"]


@pytest.mark.asyncio
async def test_direct_pass_reply_gets_visible_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: False)
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(
            llm_reply_postprocess_enabled=False,
            llm_reply_trim_terminal_period_enabled=False,
        ),
    )

    async def fake_send(_bot, _group_id, text, **_kwargs):
        sent.append(str(text))
        return SimpleNamespace(message_id=1, delivered=True)

    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        fake_send,
    )

    result = await llm_delivery.deliver_llm_callback_success(
        "request-direct-pass-fallback",
        {**_task(), "speak_trigger": "to_me"},
        bot=SimpleNamespace(self_id="99"),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="PASS",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
    )

    assert result.delivered is True
    assert sent == [LLM_CHAT_EMPTY_FALLBACK]


@pytest.mark.asyncio
async def test_failed_callback_emits_fixed_output_failure_linkage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.ai_callback import runner

    events: list[dict[str, object]] = []
    monkeypatch.setattr(runner, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(
        runner.TaskManager,
        "claim_task",
        lambda _task_id: None,
    )

    async def claim_task(_task_id: str):
        return {
            **_task(),
            "request_id": "request-callback-failed",
        }

    monkeypatch.setattr(runner.TaskManager, "claim_task", claim_task)
    monkeypatch.setattr(runner, "get_bot", lambda _bot_id: None)

    result = await runner.run_ai_callback(
        "request-callback-failed",
        status="failed",
        text="provider error: secret prompt",
    )

    assert result == {"message": "ok"}
    failure = next(event for event in events if event["stage"] == "output")
    assert failure["decision"] == "failed"
    assert failure["reason"] == "callback_failed"
    assert failure["request_id_hash"]
    assert "secret prompt" not in str(events)
    assert "text" not in failure
