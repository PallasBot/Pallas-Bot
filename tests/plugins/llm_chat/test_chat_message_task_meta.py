from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pallas.product.llm.behavior import BehaviorAction, BehaviorPattern, BehaviorScene
from pallas.product.llm.reply_variation import build_recent_reply_variation_hint
from pallas.product.llm.session_store import LlmChatTurn


def test_build_recent_reply_variation_hint_flags_repeated_structure_without_exact_duplicate() -> None:
    turns = [
        LlmChatTurn(role="assistant", content="其实这事可以慢慢来，你先别急。", user_id=1, created_at=1),
        LlmChatTurn(role="assistant", content="感觉这事不用一下说满，你先收一收。", user_id=1, created_at=2),
        LlmChatTurn(role="assistant", content="确实不用讲太整套，你先按这个做。", user_id=1, created_at=3),
    ]

    hint = build_recent_reply_variation_hint(turns)

    assert "最近几轮别再用这些开头" in hint
    assert "最近解释偏满，这轮优先短一点，像顺手接一句" in hint
    assert "最近句式有点一个模子" in hint


def test_build_recent_reply_variation_hint_flags_repeated_laugh_opener() -> None:
    turns = [
        LlmChatTurn(role="assistant", content="哈哈，这事还真挺怪。", user_id=1, created_at=1),
        LlmChatTurn(role="assistant", content="哈哈，先别急。", user_id=1, created_at=2),
        LlmChatTurn(role="assistant", content="哈哈哈，你这波也太巧了。", user_id=1, created_at=3),
    ]

    hint = build_recent_reply_variation_hint(turns)

    assert "最近几轮别再用这些开头：哈哈类" in hint


def test_build_recent_reply_variation_hint_flags_repeated_sigh_opener() -> None:
    turns = [
        LlmChatTurn(role="assistant", content="欸，这也太巧了。", user_id=1, created_at=1),
        LlmChatTurn(role="assistant", content="哎，先别急。", user_id=1, created_at=2),
        LlmChatTurn(role="assistant", content="唉，你这波真离谱。", user_id=1, created_at=3),
    ]

    hint = build_recent_reply_variation_hint(turns)

    assert "最近几轮别再用这些开头：语气词类" in hint


def test_build_recent_reply_variation_hint_flags_generic_prefix_cluster() -> None:
    turns = [
        LlmChatTurn(role="assistant", content="行吧，那就先这样。", user_id=1, created_at=1),
        LlmChatTurn(role="assistant", content="行吧，你先忙。", user_id=1, created_at=2),
        LlmChatTurn(role="assistant", content="行吧，回头再说。", user_id=1, created_at=3),
    ]

    hint = build_recent_reply_variation_hint(turns)

    assert "最近几轮别再用这些开头：行吧" in hint


@pytest.mark.asyncio
async def test_handle_llm_chat_skips_empty_to_me_without_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        reply=None,
        raw_message="[CQ:at,qq=10001]",
        get_plaintext=lambda: "",
        get_message=lambda: "",
        get_session_id=lambda: "group_20002_30003",
    )
    bot = SimpleNamespace(self_id="10001")

    send_mock = AsyncMock()
    submit_mock = AsyncMock()

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(mod.llm_chat_msg, "send", send_mock)
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)

    await mod.handle_llm_chat(bot, event)

    send_mock.assert_not_awaited()
    submit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_llm_chat_skips_low_value_direct_social_before_turn_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod
    from pallas.product.llm.config import LlmConfig

    event = SimpleNamespace(
        to_me=True,
        group_id=20002,
        user_id=30003,
        reply=None,
        get_plaintext=lambda: "你好",
        get_message=lambda: "[CQ:at,qq=10001] 你好",
        get_session_id=lambda: "group_20002_30003",
    )
    bot = SimpleNamespace(self_id="10001")

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_llm_chat_config",
        lambda: SimpleNamespace(llm_chat_system_prompt_path="", llm_chat_min_priority=40),
    )
    monkeypatch.setattr(mod, "get_llm_config", lambda: LlmConfig(llm_chat_enabled=True))
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(return_value=(SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})), None, None)),
    )
    monkeypatch.setattr(
        mod,
        "evaluate_llm_reply_gate_result",
        lambda *_args, **_kwargs: SimpleNamespace(decision="proceed", reason=""),
    )
    monkeypatch.setattr(mod, "check_llm_chat_gate", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "list_user_llm_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod, "latest_llm_assistant_reply", AsyncMock(return_value=""))
    monkeypatch.setattr(
        "pallas.product.llm.repeater_persona_context.load_recent_bot_plain_replies",
        AsyncMock(return_value=[]),
    )
    turn_decision = AsyncMock(side_effect=AssertionError("low-value social turn must not reach the model"))
    monkeypatch.setattr(mod, "decide_current_turn_with_model", turn_decision)
    submit_mock = AsyncMock()
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)

    await mod.handle_llm_chat(bot, event)

    turn_decision.assert_not_awaited()
    submit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_llm_chat_submits_required_tool_intent_despite_low_social_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.llm_chat import chat_message as mod
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.current_turn_decision import (
        CurrentTurnAction,
        CurrentTurnDecision,
        CurrentTurnDecisionTrace,
        CurrentTurnSocialAction,
    )

    event = SimpleNamespace(
        to_me=True,
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        reply=None,
        get_plaintext=lambda: "牛牛赞我",
        get_message=lambda: "[CQ:at,qq=10001] 牛牛赞我",
        get_session_id=lambda: "group_20002_30003",
    )
    bot = SimpleNamespace(self_id="10001")

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_llm_chat_config",
        lambda: SimpleNamespace(llm_chat_system_prompt_path="", llm_chat_min_priority=40),
    )
    monkeypatch.setattr(mod, "get_llm_config", lambda: LlmConfig(llm_chat_enabled=True))
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(return_value=(SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})), None, None)),
    )
    monkeypatch.setattr(
        mod,
        "evaluate_llm_reply_gate_result",
        lambda *_args, **_kwargs: SimpleNamespace(decision="proceed", reason=""),
    )
    monkeypatch.setattr(mod, "check_llm_chat_gate", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "refresh_llm_chat_cooldown", AsyncMock())
    monkeypatch.setattr(mod, "list_user_llm_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod, "latest_llm_assistant_reply", AsyncMock(return_value=""))
    monkeypatch.setattr(mod.TaskManager, "add_task", AsyncMock())
    monkeypatch.setattr(mod, "maybe_auto_save_episode", AsyncMock())
    monkeypatch.setattr(mod, "resolve_login_nickname", AsyncMock(return_value=""))
    monkeypatch.setattr(
        "pallas.product.llm.repeater_persona_context.load_recent_bot_plain_replies",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        mod,
        "assemble_tool_bundle",
        lambda **_kwargs: {
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "interact.praise"}}],
            "tool_choice_prefer": "required",
        },
    )
    turn_decision = AsyncMock(
        return_value=CurrentTurnDecision(
            action=CurrentTurnAction.TOOL,
            social_action=CurrentTurnSocialAction.ANSWER,
            trace=CurrentTurnDecisionTrace(
                action=CurrentTurnAction.TOOL,
                social_action=CurrentTurnSocialAction.ANSWER,
                source="rule",
                reason="required_tool_intent",
            ),
        )
    )
    monkeypatch.setattr(mod, "decide_current_turn_with_model", turn_decision)
    monkeypatch.setattr(
        mod,
        "assemble_direct_chat_context",
        AsyncMock(
            return_value=SimpleNamespace(
                system_prompt="sys",
                knowledge_retrieval_trace={},
                hybrid_retrieval_trace={},
                relationship_trace={},
            )
        ),
    )
    monkeypatch.setattr(mod, "resolve_conversation_feature_level", lambda *_args: "full_conversation_kernel")
    monkeypatch.setattr(mod, "can_read_behavioral_learning", lambda *_args: False)
    submit_mock = AsyncMock(return_value=SimpleNamespace(ok=True, task_id="ai-task-1", status="queued"))
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)

    await mod.handle_llm_chat(bot, event)

    turn_decision.assert_awaited_once()
    submit_mock.assert_awaited_once()
    assert submit_mock.await_args.args[0].tool_metadata["tools_enabled"] is True


@pytest.mark.asyncio
async def test_handle_llm_chat_records_route_and_fallback_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        raw_message="[CQ:at,qq=10001] 你还在吗",
        get_plaintext=lambda: "你还在吗",
        get_message=lambda: "[CQ:at,qq=10001] 你还在吗",
        get_session_id=lambda: "group_20002_30003",
    )
    bot = SimpleNamespace(self_id="10001")

    added: dict[str, object] = {}

    async def fake_add_task(task_id: str, payload: dict) -> None:
        added["task_id"] = task_id
        added["payload"] = payload

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_llm_chat_config",
        lambda: SimpleNamespace(
            llm_chat_system_prompt_path="",
            llm_chat_min_priority=40,
        ),
    )
    monkeypatch.setattr(
        mod,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_memory_rag_enabled=False,
            llm_relationship_notes_enabled=False,
            llm_chat_enabled=True,
            llm_select_enabled=True,
            llm_polish_lite_enabled=False,
            llm_polish_enabled=False,
            llm_chat_cooldown_sec=3,
            llm_chat_queue_merge=True,
            llm_speak_followup_enabled=False,
            llm_speak_followup_window_sec=30,
            llm_speak_followup_max_total_sec=120,
            llm_speak_perception_enabled=False,
        ),
    )
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(
            return_value=(
                SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})),
                None,
                None,
            )
        ),
    )
    decision_called: list[bool] = []

    async def fake_context(*_args, **kwargs) -> SimpleNamespace:
        assert decision_called, "current turn decision must run before context assembly"
        assert kwargs["allow_persistent_memory"] is False
        return SimpleNamespace(
            system_prompt="sys",
            knowledge_retrieval_trace={"hit_count": 1},
            hybrid_retrieval_trace={"sources": ["memory"]},
            relationship_trace={},
        )

    async def fake_current_turn_decision(*_args, **_kwargs):
        decision_called.append(True)
        return SimpleNamespace(
            action=mod.CurrentTurnAction.REPLY,
            social_action="ACK",
            trace=SimpleNamespace(
                model_dump=lambda **_kwargs: {
                    "action": "REPLY",
                    "social_action": "ACK",
                    "source": "test",
                    "reason": "test",
                }
            ),
        )

    monkeypatch.setattr(mod, "decide_current_turn_with_model", fake_current_turn_decision)
    monkeypatch.setattr(mod, "assemble_direct_chat_context", fake_context)
    monkeypatch.setattr(
        mod,
        "classify_behavior_scene",
        lambda **_kwargs: BehaviorScene.PROVOCATION,
    )
    monkeypatch.setattr(
        mod,
        "select_behavior_patterns",
        lambda **_kwargs: [
            BehaviorPattern(
                pattern_id="p1",
                scene=BehaviorScene.PROVOCATION,
                action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
                scope_group_id=20002,
                success_score=3,
            )
        ],
    )
    monkeypatch.setattr(mod, "GroupMessageEvent", SimpleNamespace)
    monkeypatch.setattr(mod, "resolve_conversation_feature_level", lambda *_args, **_kwargs: "full_conversation_kernel")
    feedback_hint = Mock(return_value="【维护者样本参考】\n- 可写一句群内短梗。")
    monkeypatch.setattr(mod, "build_group_feedback_chat_hint", feedback_hint, raising=False)
    monkeypatch.setattr(mod, "can_read_behavioral_learning", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        mod,
        "evaluate_llm_reply_gate_result",
        lambda *_args, **_kwargs: SimpleNamespace(decision="proceed", reason=""),
    )
    monkeypatch.setattr(mod, "check_llm_chat_gate", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "refresh_llm_chat_cooldown", AsyncMock())
    monkeypatch.setattr(
        mod,
        "merge_queued_chat",
        lambda *_args, **_kwargs: SimpleNamespace(text="[CQ:at,qq=10001] 你还在吗", merged=False),
    )
    monkeypatch.setattr(
        mod,
        "list_user_llm_messages",
        AsyncMock(
            return_value=[
                SimpleNamespace(role="assistant", content="其实就是这样", user_id=30003, created_at=1),
                SimpleNamespace(role="assistant", content="其实也行", user_id=30003, created_at=2),
                SimpleNamespace(role="assistant", content="其实差不多。", user_id=30003, created_at=3),
            ]
        ),
    )
    monkeypatch.setattr(mod, "latest_llm_assistant_reply", AsyncMock(return_value="上一句"))
    monkeypatch.setattr(
        "pallas.product.llm.repeater_semantic_style.resolve_cached_semantic_style",
        lambda *_args, **_kwargs: SimpleNamespace(
            style_anchor="短句轻怼。",
            prompt_block="【本群表达校准】\n保持：短句轻怼。",
            direct_candidate="没救了",
        ),
    )
    monkeypatch.setattr(
        "pallas.product.llm.repeater_persona_context.load_recent_bot_plain_replies",
        AsyncMock(return_value=["群内上一句", "群内更早一句"]),
    )
    submit_mock = AsyncMock(return_value=SimpleNamespace(ok=True, task_id="ai-task-1", status="queued"))
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)
    monkeypatch.setattr(mod.TaskManager, "add_task", fake_add_task)

    await mod.handle_llm_chat(bot, event)

    payload = added["payload"]
    assert isinstance(payload, dict)
    assert payload["task_type"] == "llm_chat"
    assert payload["fallback_text"] == ""
    assert payload["llm_route"] == "plain_llm_chat"
    assert payload["last_reply_text"] == "上一句"
    assert payload["recent_reply_texts"] == ["群内上一句", "群内更早一句"]
    assert "variation_hint" not in payload
    assert payload["behavior_scene"] == "provocation"
    assert payload["behavior_pattern_ids"] == ["p1"]
    assert payload["behavior_actions"] == ["light_tease_and_close"]
    assert payload["behavior_hint"]
    assert "persona_affect_block" not in payload
    assert payload["current_turn_trace"]["social_action"] == "ACK"
    assert payload["reply_delivery_style"] == "PLAIN"
    assert payload["message_id"] == 40004
    feedback_hint.assert_not_called()
    submit_request = submit_mock.await_args.args[0]
    assert "【本轮表达去重】" not in submit_request.system_prompt
    assert "【本轮牛格塑形】" not in submit_request.system_prompt
    assert "【表达习惯参考】" not in submit_request.system_prompt
    assert "【收尾变化参考】" not in submit_request.system_prompt
    assert "【语料收尾参考】" not in submit_request.system_prompt
    assert "【本群表达校准】" in submit_request.system_prompt
    assert "【本轮表达去重】" not in "\n".join(submit_request.style_user_hints)
    assert "【收尾变化参考】" not in "\n".join(submit_request.style_user_hints)
    assert "本轮直接回答当前问题，别补一整套客套。" not in "\n".join(submit_request.style_user_hints)
    assert "【本轮临时措辞】" not in "\n".join(submit_request.style_user_hints)
    assert submit_request.style_user_hints == []
    assert "persona_shaping_active" not in submit_request.llm_rewrite_metadata
    assert "variation_hint" not in submit_request.llm_rewrite_metadata
    assert "same_utterance_redup" not in submit_request.llm_rewrite_metadata
    assert submit_request.llm_rewrite_metadata["social_action"] == "ACK"
    assert submit_request.llm_rewrite_metadata["reply_target"] == "fact"
    assert submit_request.llm_rewrite_metadata["semantic_style_direct_candidate"] == "没救了"
    assert submit_request.include_session_history is False
    assert submit_request.hybrid_retrieval_trace["sources"] == ["memory"]


@pytest.mark.asyncio
async def test_handle_llm_chat_submits_explicit_mention_without_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        raw_message="[CQ:at,qq=10001] 等等我补一句...",
        get_plaintext=lambda: "等等我补一句...",
        get_message=lambda: "[CQ:at,qq=10001] 等等我补一句...",
        get_session_id=lambda: "group_20002_30003",
    )
    bot = SimpleNamespace(self_id="10001")

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_llm_chat_config",
        lambda: SimpleNamespace(
            llm_chat_system_prompt_path="",
            llm_chat_min_priority=40,
        ),
    )
    monkeypatch.setattr(
        mod,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_memory_rag_enabled=False,
            llm_relationship_notes_enabled=False,
            llm_chat_enabled=True,
            llm_select_enabled=False,
            llm_polish_lite_enabled=False,
            llm_polish_enabled=False,
            llm_chat_cooldown_sec=3,
            llm_chat_queue_merge=True,
            llm_speak_followup_enabled=False,
            llm_speak_followup_window_sec=30,
            llm_speak_followup_max_total_sec=120,
            llm_speak_perception_enabled=False,
        ),
    )
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(
            return_value=(
                SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})),
                None,
                None,
            )
        ),
    )
    monkeypatch.setattr(
        mod,
        "assemble_direct_chat_context",
        AsyncMock(
            return_value=SimpleNamespace(
                system_prompt="sys",
                knowledge_retrieval_trace={},
                hybrid_retrieval_trace={},
                relationship_trace={},
            )
        ),
    )
    monkeypatch.setattr(mod, "resolve_conversation_feature_level", lambda *_args, **_kwargs: "full_conversation_kernel")
    monkeypatch.setattr(mod, "can_read_behavioral_learning", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        mod,
        "evaluate_llm_reply_gate_result",
        lambda *_args, **_kwargs: SimpleNamespace(decision="proceed", reason=""),
    )
    monkeypatch.setattr(mod, "check_llm_chat_gate", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "refresh_llm_chat_cooldown", AsyncMock())
    monkeypatch.setattr(mod, "list_user_llm_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod, "latest_llm_assistant_reply", AsyncMock(return_value=""))
    submit_mock = AsyncMock(return_value=SimpleNamespace(ok=True, task_id="ai-task-1", status="queued"))
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)

    await mod.handle_llm_chat(bot, event)

    submit_mock.assert_awaited_once()
