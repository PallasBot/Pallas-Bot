from __future__ import annotations

import time

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PokeNotifyEvent
from nonebot.exception import IgnoredException

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.reply_gate import evaluate_llm_reply_gate_result
from pallas.product.llm.shut_up import is_shut_up_text, is_speak_request_text
from pallas.product.llm.silence import (
    clear_all_silences,
    is_group_silenced,
    silence_remaining_sec,
    trigger_silence,
    try_clear_silence,
)
from pallas.product.llm.silence_gate import suppress_group_silence


def _cfg(
    *,
    enabled: bool = True,
    min_sec: int = 30,
    max_sec: int = 300,
) -> LlmConfig:
    return LlmConfig(
        llm_reply_gate_enabled=True,
        llm_reply_gate_min_chars=0,
        llm_shut_up_silence_enabled=enabled,
        llm_shut_up_silence_min_sec=min_sec,
        llm_shut_up_silence_max_sec=max_sec,
    )


def test_shut_up_text_detection() -> None:
    assert is_shut_up_text("闭嘴") is True
    assert is_shut_up_text("别说话") is True
    assert is_shut_up_text("牛牛，你能不能不要说话") is True
    assert is_speak_request_text("牛牛，你能不能不要说话") is False
    assert is_shut_up_text("今天吃什么") is False


def test_speak_request_text() -> None:
    assert is_speak_request_text("牛牛，说话") is True
    assert is_speak_request_text("回话！") is True
    assert is_speak_request_text("别沉默") is True
    assert is_speak_request_text("闭嘴") is False
    assert is_speak_request_text("你不要说话") is False
    assert is_speak_request_text("今天天气不错") is False


def test_trigger_and_query_silence() -> None:
    clear_all_silences()
    bot_id, group_id = 10001, 20001
    seconds = trigger_silence(bot_id, group_id, min_sec=30, max_sec=30)
    assert seconds == 30
    assert is_group_silenced(bot_id, group_id) is True
    remaining = silence_remaining_sec(bot_id, group_id)
    assert 0 < remaining <= 30
    clear_all_silences()
    assert is_group_silenced(bot_id, group_id) is False


def test_silence_expires_automatically(monkeypatch) -> None:
    clear_all_silences()
    bot_id, group_id = 10001, 20001

    real_monotonic = time.monotonic
    now = [1000.0]

    def fake_monotonic() -> float:
        return now[0]

    monkeypatch.setattr("pallas.product.llm.silence.time.monotonic", fake_monotonic)
    trigger_silence(bot_id, group_id, min_sec=30, max_sec=30)
    assert is_group_silenced(bot_id, group_id) is True
    now[0] += 31
    assert is_group_silenced(bot_id, group_id) is False
    monkeypatch.setattr("pallas.product.llm.silence.time.monotonic", real_monotonic)


def test_try_clear_silence() -> None:
    clear_all_silences()
    bot_id, group_id = 10001, 20001
    assert try_clear_silence(bot_id, group_id) is False
    trigger_silence(bot_id, group_id, min_sec=30, max_sec=30)
    assert try_clear_silence(bot_id, group_id) is True
    assert is_group_silenced(bot_id, group_id) is False


def test_reply_gate_triggers_silence() -> None:
    clear_all_silences()
    bot_id, group_id = 10001, 20001
    result = evaluate_llm_reply_gate_result(
        "闭嘴",
        cfg=_cfg(min_sec=1, max_sec=1),
        bot_id=bot_id,
        group_id=group_id,
    )
    assert result.decision == "skip"
    assert result.reason == "shut_up"
    assert is_group_silenced(bot_id, group_id) is True


def test_reply_gate_respects_disabled_silence() -> None:
    clear_all_silences()
    bot_id, group_id = 10001, 20001
    result = evaluate_llm_reply_gate_result(
        "闭嘴",
        cfg=_cfg(enabled=False, min_sec=1, max_sec=1),
        bot_id=bot_id,
        group_id=group_id,
    )
    assert result.decision == "skip"
    assert is_group_silenced(bot_id, group_id) is False


def _make_group_message_event(text: str, *, group_id: int = 20001, user_id: int = 501) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1,
        self_id=10001,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=user_id,
        message=text,
        raw_message=text,
        font=0,
        sender={"user_id": user_id, "nickname": "a", "card": "", "role": "member"},
        group_id=group_id,
    )


def _fake_bot(*, self_id: int = 10001):
    bot = type("FakeBot", (), {})()
    bot.self_id = self_id
    return bot


async def test_gate_suppresses_active_message_in_silenced_group() -> None:
    clear_all_silences()
    bot = _fake_bot()
    trigger_silence(10001, 20001, min_sec=30, max_sec=30)
    event = _make_group_message_event("大家好")
    with pytest.raises(IgnoredException):
        await suppress_group_silence(bot, event)
    clear_all_silences()


async def test_gate_passes_command_in_silenced_group() -> None:
    clear_all_silences()
    bot = _fake_bot()
    trigger_silence(10001, 20001, min_sec=30, max_sec=30)
    event = _make_group_message_event("/帮我看看今天运势")
    assert await suppress_group_silence(bot, event) is None
    clear_all_silences()


async def test_gate_passes_speak_request_and_clears_silence() -> None:
    clear_all_silences()
    bot = _fake_bot()
    trigger_silence(10001, 20001, min_sec=30, max_sec=30)
    assert is_group_silenced(10001, 20001) is True
    event = _make_group_message_event("牛牛说话")
    assert await suppress_group_silence(bot, event) is None
    assert is_group_silenced(10001, 20001) is False


async def test_gate_passes_normal_message_when_not_silenced() -> None:
    clear_all_silences()
    bot = _fake_bot()
    event = _make_group_message_event("大家好")
    assert await suppress_group_silence(bot, event) is None


async def test_gate_ignores_non_v11_event() -> None:
    clear_all_silences()
    bot = _fake_bot()
    trigger_silence(10001, 20001, min_sec=30, max_sec=30)

    class FakeOtherEvent:
        __module__ = "nonebot.adapters.kaiheila"

    assert await suppress_group_silence(bot, FakeOtherEvent()) is None
    clear_all_silences()


async def test_gate_suppresses_poke_in_silenced_group() -> None:
    clear_all_silences()
    bot = _fake_bot()
    trigger_silence(10001, 20001, min_sec=30, max_sec=30)
    poke = PokeNotifyEvent(
        time=1,
        self_id=10001,
        post_type="notice",
        notice_type="notify",
        user_id=501,
        group_id=20001,
        target_id=10001,
        sub_type="poke",
        raw_message="",
    )
    with pytest.raises(IgnoredException):
        await suppress_group_silence(bot, poke)
    clear_all_silences()
