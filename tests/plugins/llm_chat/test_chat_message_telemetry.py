from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.turn_telemetry import build_turn_event


def _event(text: str, *, to_me: bool = False, group_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        to_me=to_me,
        self_id="10001",
        group_id=group_id,
        user_id=30003,
        message_id=40004,
        reply=None,
        raw_message=text,
        get_plaintext=lambda: text,
        get_message=lambda: text,
        get_session_id=lambda: "group_20002_30003",
    )


def _llm_config(**overrides: object) -> SimpleNamespace:
    values = {
        "llm_chat_enabled": True,
        "llm_chat_cooldown_sec": 3,
        "llm_chat_queue_merge": False,
        "llm_memory_rag_enabled": False,
        "llm_relationship_notes_enabled": False,
        "llm_speak_followup_enabled": False,
        "llm_speak_followup_window_sec": 45,
        "llm_speak_followup_max_total_sec": 180,
        "llm_speak_perception_enabled": False,
        "llm_speak_mention_enabled": False,
        "llm_speak_min_alias_len": 2,
        "llm_speak_ambient_enabled": False,
        "llm_speak_ambient_rate": 0.0,
        "llm_speak_ambient_min_score": 0,
        "llm_speak_ambient_cooldown_sec": 0,
        "llm_speak_ambient_budget_limit": 0,
        "llm_speak_ambient_budget_window_sec": 900,
        "llm_chat_system_prompt_path": "",
        "llm_chat_min_priority": 40,
        "llm_current_turn_decision_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _capture_events(events: list[dict[str, object]]):
    def capture(**fields: object) -> None:
        events.append(build_turn_event(hash_key=b"test-telemetry-key", **fields))

    return capture


def _install_common_handle_stubs(monkeypatch: pytest.MonkeyPatch, mod) -> None:
    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(mod, "get_llm_chat_config", lambda: _llm_config())
    monkeypatch.setattr(mod, "get_llm_config", lambda: _llm_config())
    monkeypatch.setattr(mod, "parse_memory_teach", lambda _text: None)
    monkeypatch.setattr(mod, "parse_relationship_teach", lambda _text: None)
    monkeypatch.setattr(mod, "save_self_alias_from_teach", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "save_peer_alias_from_teach", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "maybe_persist_self_alias_from_utterance", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "schedule_persist_relationship_from_utterance", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "begin_chat_turn", lambda *args: True)


@pytest.mark.asyncio
async def test_handle_emits_ingress_before_prepare_with_privacy_safe_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    _install_common_handle_stubs(monkeypatch, mod)
    captured: list[object] = []

    def fake_create_task(coro, *, name=None):
        captured.append(coro)
        return SimpleNamespace(add_done_callback=lambda _callback: None)

    events: list[dict[str, object]] = []
    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(mod, "record_turn_event", _capture_events(events))
    bot = SimpleNamespace(self_id="10001")

    await mod.handle_llm_chat(bot, _event("在吗", to_me=True, group_id=20002))

    assert captured
    ingress = next(event for event in events if event["stage"] == "ingress")
    assert ingress["decision"] == "accepted"
    assert ingress["is_to_me"] is True
    assert ingress["turn_id"]
    assert "text" not in ingress
    assert all(event["turn_id"] == ingress["turn_id"] for event in events)
    for coro in captured:
        coro.close()


@pytest.mark.asyncio
async def test_handle_emits_speak_proceed_for_direct_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    _install_common_handle_stubs(monkeypatch, mod)
    captured: list[object] = []

    def fake_create_task(coro, *, name=None):
        captured.append(coro)
        return SimpleNamespace(add_done_callback=lambda _callback: None)

    events: list[dict[str, object]] = []
    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(mod, "record_turn_event", _capture_events(events))

    await mod.handle_llm_chat(SimpleNamespace(self_id="10001"), _event("在吗", to_me=True, group_id=20002))

    ingress = next(event for event in events if event["stage"] == "ingress")
    speak = next(event for event in events if event["stage"] == "speak")
    assert speak["decision"] == "proceed"
    assert speak["reason"] == "to_me"
    assert speak["turn_id"] == ingress["turn_id"]
    assert speak["is_to_me"] is True
    for coro in captured:
        coro.close()


@pytest.mark.asyncio
async def test_handle_emits_speak_skip_for_ambient_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    _install_common_handle_stubs(monkeypatch, mod)
    monkeypatch.setattr(mod, "_resolve_speak_aliases", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "pallas.product.llm.ambient_turn_window.note_ambient_turn_and_should_flush",
        lambda **kwargs: (True, None),
    )
    monkeypatch.setattr(
        "pallas.product.llm.speak_perception.text_mentions_aliases",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        mod,
        "get_llm_config",
        lambda: _llm_config(
            llm_speak_perception_enabled=True,
            llm_speak_ambient_enabled=True,
        ),
    )
    monkeypatch.setattr(
        mod,
        "evaluate_speak_perception",
        lambda **kwargs: SimpleNamespace(should_speak=False, reason="ambient_probability", score=3),
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(mod, "record_turn_event", _capture_events(events))

    await mod.handle_llm_chat(SimpleNamespace(self_id="10001"), _event("哈哈", group_id=20002))

    ingress = next(event for event in events if event["stage"] == "ingress")
    speak = next(event for event in events if event["stage"] == "speak")
    assert speak["decision"] == "skip"
    assert speak["reason"] == "ambient_probability"
    assert speak["turn_id"] == ingress["turn_id"]
    assert speak["shape"] == ingress["shape"]
    assert "text" not in speak


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gate_decision", "expected_decision", "expected_reason"),
    [("skip", "skip", "noise"), ("defer", "defer", "wait_for_more")],
)
async def test_prepare_emits_reply_gate_terminal_event(
    monkeypatch: pytest.MonkeyPatch,
    gate_decision: str,
    expected_decision: str,
    expected_reason: str,
) -> None:
    from packages.llm_chat import chat_message as mod

    events: list[dict[str, object]] = []
    monkeypatch.setattr(mod, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(return_value=(SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})), None, None)),
    )
    monkeypatch.setattr(mod, "get_system_prompt", lambda: "sys")
    monkeypatch.setattr(
        mod,
        "evaluate_llm_reply_gate_result",
        lambda *args, **kwargs: SimpleNamespace(decision=gate_decision, reason="noise"),
    )
    monkeypatch.setattr(mod, "should_wait_for_more", lambda *args, **kwargs: gate_decision == "defer")
    monkeypatch.setattr(mod, "record_bot_llm_task", lambda *args: None)

    await mod.prepare_and_submit_llm_chat_turn(
        bot=SimpleNamespace(self_id="10001"),
        event=_event("???", to_me=False, group_id=20002),
        msg="???",
        plain="???",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        is_to_me=False,
        speak_trigger="ambient",
        turn_id="turn-gate",
        llm_cfg=_llm_config(),
        chat_cfg=SimpleNamespace(llm_chat_system_prompt_path=""),
    )

    gate_event = next(event for event in events if event["stage"] == "reply_gate")
    assert gate_event["decision"] == expected_decision
    assert gate_event["reason"] == expected_reason
    assert gate_event["turn_id"] == "turn-gate"
    assert "text" not in gate_event


@pytest.mark.asyncio
async def test_prepare_emits_necessity_skip_without_low_engagement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    events: list[dict[str, object]] = []
    monkeypatch.setattr(mod, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(return_value=(SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})), None, None)),
    )
    monkeypatch.setattr(
        mod, "evaluate_llm_reply_gate_result", lambda *args, **kwargs: SimpleNamespace(decision="proceed")
    )
    monkeypatch.setattr(mod, "should_wait_for_more", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "check_llm_chat_gate", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "list_user_llm_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod, "assemble_tool_bundle", lambda **kwargs: {"tools_enabled": False, "tool_schemas": []})
    monkeypatch.setattr(
        mod,
        "evaluate_reply_necessity_gate",
        lambda **kwargs: SimpleNamespace(decision="skip", score=-40, detail="noise-40"),
    )
    monkeypatch.setattr(mod, "record_bot_llm_task", lambda *args: None)

    await mod.prepare_and_submit_llm_chat_turn(
        bot=SimpleNamespace(self_id="10001"),
        event=_event("???", group_id=None),
        msg="???",
        plain="???",
        group_id=None,
        user_id=30003,
        message_id=40004,
        is_to_me=False,
        speak_trigger="ambient",
        turn_id="turn-necessity",
        llm_cfg=_llm_config(),
        chat_cfg=SimpleNamespace(llm_chat_system_prompt_path=""),
    )

    necessity_event = next(event for event in events if event["stage"] == "necessity")
    assert necessity_event["decision"] == "skip"
    assert necessity_event["necessity"] == {"score": -40, "factors": ["noise-40"]}
    assert necessity_event["turn_id"] == "turn-necessity"
    assert "text" not in necessity_event


@pytest.mark.asyncio
async def test_prepare_emits_low_engagement_necessity_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod

    events: list[dict[str, object]] = []
    monkeypatch.setattr(mod, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(return_value=(SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})), None, None)),
    )
    monkeypatch.setattr(
        mod, "evaluate_llm_reply_gate_result", lambda *args, **kwargs: SimpleNamespace(decision="proceed")
    )
    monkeypatch.setattr(mod, "should_wait_for_more", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "check_llm_chat_gate", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "list_user_llm_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod, "assemble_tool_bundle", lambda **kwargs: {"tools_enabled": False, "tool_schemas": []})
    monkeypatch.setattr(
        mod,
        "evaluate_reply_necessity_gate",
        lambda **kwargs: SimpleNamespace(decision="skip", score=-35, detail="low_social-35"),
    )
    monkeypatch.setattr(mod, "record_bot_llm_task", lambda *args: None)
    monkeypatch.setattr(
        "packages.repeater.opportunity_trace.append_conversation_decision_trace",
        lambda _trace: None,
    )
    monkeypatch.setattr(
        "pallas.product.llm.low_engagement.can_bubble_low_engagement_on_necessity_skip",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.low_engagement.dispatch_low_engagement",
        AsyncMock(return_value=True),
    )

    await mod.prepare_and_submit_llm_chat_turn(
        bot=SimpleNamespace(self_id="10001"),
        event=_event("今天好闲", group_id=20002),
        msg="今天好闲",
        plain="今天好闲",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        is_to_me=False,
        speak_trigger="ambient",
        turn_id="turn-low-engagement",
        llm_cfg=_llm_config(),
        chat_cfg=SimpleNamespace(llm_chat_system_prompt_path=""),
    )

    necessity_event = next(event for event in events if event["stage"] == "necessity")
    assert necessity_event["decision"] == "low_engagement"
    assert necessity_event["reason"] == "low_engagement"
    assert necessity_event["necessity"] == {"score": -35, "factors": ["low_social-35"]}
    assert necessity_event["turn_id"] == "turn-low-engagement"
