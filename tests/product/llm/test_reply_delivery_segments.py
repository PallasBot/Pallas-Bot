from __future__ import annotations

from unittest.mock import AsyncMock, Mock, call

import pytest

from pallas.product.llm import delivery as llm_delivery
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.webui_config import LlmWebuiConfig


def test_bubble_delay_is_human_like_and_bounded() -> None:
    import random

    short = llm_delivery.bubble_delay_seconds("好", rng=random.Random(1))
    long = llm_delivery.bubble_delay_seconds("这是一段稍长一些的回复内容", rng=random.Random(1))
    very_long = llm_delivery.bubble_delay_seconds("很长" * 100, rng=random.Random(1))

    assert short < long
    assert short >= 0.5
    assert short <= 3.5
    assert long >= 0.5
    assert long <= 3.5
    assert very_long <= 3.5

    # 随机性：相同长度不同种子产生不同间隔
    seeds = [llm_delivery.bubble_delay_seconds("好", rng=random.Random(i)) for i in range(5)]
    assert len(set(seeds)) > 1


def test_bubble_delay_reads_llm_config(monkeypatch) -> None:
    import random

    class _FakeConfig:
        llm_bubble_delay_base_sec = 2.0
        llm_bubble_delay_per_char = 0.1
        llm_bubble_delay_jitter = 0.0

    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: _FakeConfig())

    # total = 2.0 + 10*0.1 = 3.0；jitter=0 无抖动
    delay = llm_delivery.bubble_delay_seconds("一二三四五六七八九十", rng=random.Random(1))
    assert delay == 3.0


def test_reply_postprocess_schema_no_longer_advertises_sentence_splitting() -> None:
    description = str(LlmWebuiConfig.model_fields["llm_reply_postprocess_enabled"].description or "")

    assert "拆" not in description


@pytest.mark.asyncio
async def test_delivery_keeps_short_punctuated_reply_as_one_bubble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = AsyncMock(
        return_value=type("Receipt", (), {"delivered": True, "message_id": 10})(),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(llm_reply_trim_terminal_period_enabled=False),
    )

    reply_text, _text_delivered, _delivered = await llm_delivery.deliver_llm_callback_success(
        "task-natural-bubbles",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "reply_total_length_band": "short",
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="六点？你真狠。我努力一下。",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert [call.args[2] for call in sender.await_args_list] == ["六点？你真狠。我努力一下。"]
    assert reply_text == "六点？你真狠。我努力一下。"


@pytest.mark.asyncio
async def test_drunk_reply_splits_into_bubbles_and_extracts_sticker(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = AsyncMock(
        side_effect=[
            type("Receipt", (), {"delivered": True, "message_id": 10})(),
            type("Receipt", (), {"delivered": True, "message_id": 11})(),
        ]
    )
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(
            llm_reply_trim_terminal_period_enabled=False,
            llm_chat_sticker_enabled=False,
            llm_reply_split_randomize_enabled=False,
        ),
    )

    reply_text, _text_delivered, _delivered = await llm_delivery.deliver_llm_callback_success(
        "task-drunk-bubbles",
        {
            "task_type": "chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "reply_total_length_band": "short",
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="我真不行了\n再来一杯也行\n[表情：得意]",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert [call.args[2] for call in sender.await_args_list] == ["我真不行了", "再来一杯也行"]
    assert reply_text == "我真不行了\n再来一杯也行"


@pytest.mark.asyncio
async def test_delivery_keeps_complete_reply_as_one_bubble(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = AsyncMock(return_value=type("Receipt", (), {"delivered": True, "message_id": 10})())
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_split_randomize_enabled=False,
        ),
    )

    await llm_delivery.deliver_llm_callback_success(
        "task-complete-reply",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "reply_total_length_band": "complete",
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="这个参数需要先填写地址，再保存并重启服务。",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert [call.args[2] for call in sender.await_args_list] == ["这个参数需要先填写地址，再保存并重启服务。"]


@pytest.mark.asyncio
async def test_delivery_registers_each_successful_text_bubble_for_reply_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # noqa: E501
    sender = AsyncMock(
        return_value=type("Receipt", (), {"delivered": True, "message_id": 70001})(),
    )
    recorder = Mock()
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(
        "pallas.product.llm.bot_reply_context.record_bot_reply_context",
        recorder,
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(llm_reply_trim_terminal_period_enabled=False),
    )

    await llm_delivery.deliver_llm_callback_success(
        "task-context-bubbles",
        {
            "task_type": "llm_chat",
            "bot_id": 10001,
            "group_id": 20002,
            "user_id": 7,
            "reply_total_length_band": "short",
        },
        bot=object(),
        group_id=20002,
        bot_id=10001,
        bot_id_str="10001",
        text="第一句。第二句。",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert recorder.call_args_list == [
        call(group_id=20002, bot_id=10001, message_id=70001, text="第一句。第二句。"),
    ]


@pytest.mark.asyncio
async def test_delivery_splits_complete_multiline_reply_into_bubbles(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = AsyncMock(
        side_effect=[
            type("Receipt", (), {"delivered": True, "message_id": 10})(),
            type("Receipt", (), {"delivered": True, "message_id": 11})(),
        ]
    )
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_split_randomize_enabled=False,
        ),
    )

    reply_text, _text_delivered, _delivered = await llm_delivery.deliver_llm_callback_success(
        "task-complete-multiline",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "reply_total_length_band": "complete",
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="什么新牛\n你当这是牛棚呢，还带批发的",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert [call.args[2] for call in sender.await_args_list] == ["什么新牛", "你当这是牛棚呢，还带批发的"]
    assert reply_text == "什么新牛\n你当这是牛棚呢，还带批发的"


@pytest.mark.asyncio
async def test_delivery_splits_short_cjk_space_reply_into_bubbles(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = AsyncMock(
        side_effect=[
            type("Receipt", (), {"delivered": True, "message_id": 10})(),
            type("Receipt", (), {"delivered": True, "message_id": 11})(),
        ]
    )
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(llm_reply_trim_terminal_period_enabled=False),
    )

    reply_text, _text_delivered, _delivered = await llm_delivery.deliver_llm_callback_success(
        "task-cjk-space-bubbles",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "reply_total_length_band": "short",
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="在摸鱼呀 被你抓到了嘛",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert [call.args[2] for call in sender.await_args_list] == ["在摸鱼呀", "被你抓到了嘛"]
    assert reply_text == "在摸鱼呀\n被你抓到了嘛"


@pytest.mark.asyncio
async def test_delivery_splits_complete_cjk_space_reply_into_bubbles(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = AsyncMock(
        side_effect=[
            type("Receipt", (), {"delivered": True, "message_id": 10})(),
            type("Receipt", (), {"delivered": True, "message_id": 11})(),
        ]
    )
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_split_randomize_enabled=False,
        ),
    )

    reply_text, _text_delivered, _delivered = await llm_delivery.deliver_llm_callback_success(
        "task-complete-cjk-space",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "reply_total_length_band": "complete",
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="制空最稳呀 A-10A 和 F-4S 也能玩 就是定位不太一样",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert [call.args[2] for call in sender.await_args_list] == [
        "制空最稳呀 A-10A 和 F-4S 也能玩",
        "就是定位不太一样",
    ]


@pytest.mark.asyncio
async def test_delivery_splits_cjk_space_without_band(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = AsyncMock(
        side_effect=[
            type("Receipt", (), {"delivered": True, "message_id": 10})(),
            type("Receipt", (), {"delivered": True, "message_id": 11})(),
        ]
    )
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_split_randomize_enabled=False,
        ),
    )

    reply_text, _text_delivered, _delivered = await llm_delivery.deliver_llm_callback_success(
        "task-no-band-space",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text="没玩过诶 好玩吗",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert [call.args[2] for call in sender.await_args_list] == ["没玩过诶", "好玩吗"]
    assert reply_text == "没玩过诶\n好玩吗"


@pytest.mark.asyncio
async def test_multi_bubble_history_uses_one_logical_assistant_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    append = AsyncMock(return_value=True)
    sender = AsyncMock(
        side_effect=[
            type("Receipt", (), {"delivered": True, "message_id": 10})(),
            type("Receipt", (), {"delivered": True, "message_id": 11})(),
        ]
    )
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(llm_delivery, "append_llm_message", append)
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: True)

    await llm_delivery.deliver_llm_callback_success(
        "task-session-bubbles",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "user_text": "在吗",
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text='{"reply_segments":["在","咋了"]}',
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert append.await_args_list == [
        ((99, 42, 7, "user", "在吗"), {}),
        ((99, 42, 7, "assistant", "在\n咋了"), {}),
    ]


@pytest.mark.asyncio
async def test_multi_bubble_behavior_records_logical_text_and_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = AsyncMock(
        side_effect=[
            type("Receipt", (), {"delivered": True, "message_id": 10})(),
            type("Receipt", (), {"delivered": True, "message_id": 11})(),
        ]
    )
    recorded: list[object] = []
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: False)
    monkeypatch.setattr(llm_delivery, "append_behavior_run", recorded.append)

    await llm_delivery.deliver_llm_callback_success(
        "task-behavior-bubbles",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "behavior_scene": "banter",
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text='{"reply_segments":["行","就这样"]}',
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    run = recorded[0]
    assert run.reply_text == "行\n就这样"
    assert run.bubble_count == 2
    assert run.bubble_rhythm == "multi"


@pytest.mark.asyncio
async def test_failed_bubble_does_not_write_incomplete_logical_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = AsyncMock(
        side_effect=[
            type("Receipt", (), {"delivered": True, "message_id": 10})(),
            type("Receipt", (), {"delivered": False, "message_id": None})(),
        ]
    )
    append = AsyncMock(return_value=True)
    behavior = AsyncMock()
    expression = AsyncMock()
    feedback = AsyncMock()
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        sender,
    )
    monkeypatch.setattr(llm_delivery, "append_llm_message", append)
    monkeypatch.setattr(llm_delivery, "append_behavior_run", behavior)
    monkeypatch.setattr(llm_delivery, "should_append_llm_session", lambda _task: True)
    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: LlmConfig(llm_repeater_feedback_enabled=True))
    monkeypatch.setattr("pallas.product.persona.expression_learn.note_expression_from_utterance", expression)
    monkeypatch.setattr("pallas.product.llm.repeater_feedback.append_feedback_entry", feedback)

    _reply, text_delivered, delivered = await llm_delivery.deliver_llm_callback_success(
        "task-failed-bubbles",
        {
            "task_type": "llm_chat",
            "bot_id": 99,
            "group_id": 42,
            "user_id": 7,
            "user_text": "在吗",
            "behavior_scene": "banter",
            "source_tags": ["recent_chat"],
        },
        bot=object(),
        group_id=42,
        bot_id=99,
        bot_id_str="99",
        text='{"reply_segments":["第一条","第二条","第三条"]}',
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
        sleeper=lambda _delay: None,
    )

    assert (text_delivered, delivered) == (False, False)
    assert sender.await_count == 2
    append.assert_not_awaited()
    behavior.assert_not_called()
    expression.assert_not_awaited()
    feedback.assert_not_called()
