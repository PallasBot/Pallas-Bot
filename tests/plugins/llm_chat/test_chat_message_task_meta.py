from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pallas.product.llm.behavior import BehaviorAction, BehaviorPattern, BehaviorScene
from pallas.product.llm.reply_variation import build_recent_reply_variation_hint
from pallas.product.llm.session_store import LlmChatTurn


@pytest.fixture(autouse=True)
def _clean_chat_queue() -> None:
    from pallas.product.llm.chat_queue import clear_chat_queue_for_tests

    clear_chat_queue_for_tests()
    yield
    clear_chat_queue_for_tests()


@pytest.fixture
def capture_create_task(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    from packages.llm_chat import chat_message as mod

    captured: list[object] = []

    def fake_create_task(coro, *, name=None):
        captured.append(coro)
        return SimpleNamespace(add_done_callback=lambda _cb: None)

    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task)
    yield captured
    for coro in captured:
        if hasattr(coro, "close"):
            coro.close()


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


def test_llm_chat_rule_accepts_federated_alias_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    event = SimpleNamespace(
        to_me=False,
        _pallas_llm_alias_hard_trigger=True,
        raw_message="泰坦牛牛吃饭了没",
        get_plaintext=lambda: "泰坦牛牛吃饭了没",
    )

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)

    assert mod.llm_chat_rule(event) is True


@pytest.mark.asyncio
async def test_resolve_speak_aliases_caches_bot_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod

    repo = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(persona={"self_aliases": ["牛牛"]})))
    monkeypatch.setattr("pallas.core.foundation.db.make_bot_config_repository", lambda: repo)
    monkeypatch.setattr(mod, "resolve_login_nickname", AsyncMock(return_value=""))
    monkeypatch.setattr(mod, "resolve_cached_login_nickname", lambda _bot_id: "")
    monkeypatch.setattr(mod, "resolve_managed_display_name", lambda _bot_id: "")
    mod.clear_speak_alias_cache_for_tests()

    assert await mod._resolve_speak_aliases(10001) == ["牛牛"]
    assert await mod._resolve_speak_aliases(10001) == ["牛牛"]

    repo.get.assert_awaited_once_with(10001)


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
async def test_handle_llm_chat_sends_low_value_direct_social_to_turn_decision(
    monkeypatch: pytest.MonkeyPatch,
    capture_create_task: list[object],
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
        mod,
        "load_recent_bot_plain_replies",
        AsyncMock(return_value=[]),
    )
    turn_decision = AsyncMock(side_effect=AssertionError("explicit trigger must reach current-turn decision"))
    monkeypatch.setattr(mod, "decide_current_turn_with_model", turn_decision)
    submit_mock = AsyncMock()
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)

    await mod.handle_llm_chat(bot, event)
    assert len(capture_create_task) == 1
    await capture_create_task[0]

    turn_decision.assert_awaited_once()
    submit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_llm_chat_submits_required_tool_intent_despite_low_social_score(
    monkeypatch: pytest.MonkeyPatch,
    capture_create_task: list[object],
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
        mod,
        "load_recent_bot_plain_replies",
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
    assert len(capture_create_task) == 1
    await capture_create_task[0]

    turn_decision.assert_awaited_once()
    submit_mock.assert_awaited_once()
    assert submit_mock.await_args.args[0].tool_metadata["tools_enabled"] is True


@pytest.mark.asyncio
async def test_handle_llm_chat_records_route_and_fallback_meta(
    monkeypatch: pytest.MonkeyPatch,
    capture_create_task: list[object],
) -> None:
    from packages.llm_chat import chat_message as mod
    from pallas.product.llm.reply_target_candidates import (
        clear_reply_target_candidates,
        record_reply_target_candidate,
    )

    clear_reply_target_candidates()
    record_reply_target_candidate(group_id=20002, message_id=40003, sender_id=30004, text="配置好像有问题")

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        raw_message="[CQ:reply,id=70001][CQ:at,qq=10001] 你还在吗",
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
                SimpleNamespace(
                    system="sys",
                    sections=SimpleNamespace(
                        base="核心人格",
                        self_identity="【同伴牛牛】\n你不是其他牛牛。",
                    ),
                    metadata=SimpleNamespace(persona={}),
                ),
                None,
                None,
            )
        ),
    )
    decision_called: list[bool] = []

    async def fake_context(*_args, **kwargs) -> SimpleNamespace:
        assert decision_called, "current turn decision must run before context assembly"
        assert kwargs["allow_persistent_memory"] is False
        assert kwargs["group_timeline"] == "【刚才的群聊】\n- 兔兔：还是笨蛋欸\n【牛牛刚才说】\n复读的原话"
        return SimpleNamespace(
            system_prompt="sys",
            knowledge_retrieval_trace={"hit_count": 1},
            hybrid_retrieval_trace={"sources": ["memory"]},
            relationship_trace={},
        )

    async def fake_current_turn_decision(turn, **_kwargs):
        decision_called.append(True)
        assert [item.message_id for item in turn.reply_candidates] == [40003, 40004]
        assert turn.reply_candidates[-1].is_current is True
        return SimpleNamespace(
            action=mod.CurrentTurnAction.REPLY,
            social_action="ACK",
            delivery_style="QUOTE",
            reply_message_id=40003,
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
        "build_recent_group_timeline",
        AsyncMock(return_value="【刚才的群聊】\n- 兔兔：还是笨蛋欸"),
    )
    reply_context_lookup = Mock(return_value="复读的原话")
    monkeypatch.setattr(mod, "lookup_bot_reply_context", reply_context_lookup, raising=False)
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
        lambda *_args, **_kwargs: SimpleNamespace(text="你还在吗", merged=False),
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
    semantic_style_mock = Mock(
        return_value=SimpleNamespace(
            prompt_block="【本群表达校准】\n保持：短句轻怼。",
            matched_examples=[("又炸了", "没救了")],
            baseline_note="本群真人单条短气泡为主（占比约 100%）。",
            direct_candidate="没救了",
            source_example_id="semantic:source:1",
        )
    )
    monkeypatch.setattr(
        "pallas.product.llm.repeater_semantic_style.resolve_cached_semantic_style",
        semantic_style_mock,
    )
    monkeypatch.setattr(
        mod,
        "load_recent_bot_plain_replies",
        AsyncMock(return_value=["群内上一句", "群内更早一句"]),
    )
    submit_mock = AsyncMock(return_value=SimpleNamespace(ok=True, task_id="ai-task-1", status="queued"))
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)
    monkeypatch.setattr(mod.TaskManager, "add_task", fake_add_task)

    await mod.handle_llm_chat(bot, event)
    assert len(capture_create_task) == 1
    await capture_create_task[0]

    payload = added["payload"]
    assert isinstance(payload, dict)
    assert payload["task_type"] == "llm_chat"
    assert payload["fallback_text"] == ""
    assert payload["llm_route"] == "plain_llm_chat"
    assert payload["last_reply_text"] == "上一句"
    assert payload["recent_reply_texts"] == ["群内上一句", "群内更早一句"]
    assert semantic_style_mock.call_args.kwargs["query_text"] == "你还在吗"
    assert semantic_style_mock.call_args.kwargs["recent_assistant_replies"] == ["群内上一句", "群内更早一句"]
    assert "variation_hint" not in payload
    assert payload["behavior_scene"] == "provocation"
    assert payload["behavior_pattern_ids"] == ["p1"]
    assert payload["behavior_actions"] == ["light_tease_and_close"]
    assert payload["behavior_hint"]
    assert "persona_affect_block" not in payload
    assert payload["current_turn_trace"]["social_action"] == "ACK"
    assert payload["reply_delivery_style"] == "QUOTE"
    assert payload["message_id"] == 40004
    assert payload["reply_to_message_id"] == 40003
    assert payload["reply_candidate_ids"] == [40003, 40004]
    reply_context_lookup.assert_called_once_with(group_id=20002, bot_id=10001, message_id=70001)
    assert payload["reply_total_length_band"] == "complete"
    feedback_hint.assert_not_called()
    submit_request = submit_mock.await_args.args[0]
    assert "【本轮表达去重】" not in submit_request.system_prompt
    assert "【本轮牛格塑形】" not in submit_request.system_prompt
    assert "【表达习惯参考】" not in submit_request.system_prompt
    assert "【收尾变化参考】" not in submit_request.system_prompt
    assert "【语料收尾参考】" not in submit_request.system_prompt
    assert "【本群表达校准】" not in submit_request.system_prompt
    assert "【群表达指导】" in submit_request.system_prompt
    assert "刚才的群聊" in submit_request.system_prompt
    assert "兔兔：还是笨蛋欸" in submit_request.system_prompt
    assert "【同伴牛牛】" in submit_request.system_prompt
    assert "你不是其他牛牛。" in submit_request.system_prompt
    assert "短句轻怼。" not in submit_request.system_prompt
    assert "没救了" in submit_request.system_prompt
    assert "【回复形状与输出契约】" in submit_request.system_prompt
    assert '"reply_segments"' not in submit_request.system_prompt
    assert "直接输出一条或多条可见对白" in submit_request.system_prompt
    assert "引用只决定回复哪条消息" in submit_request.system_prompt
    assert "不要因引用把话一次说完" in submit_request.system_prompt
    assert "「行啊」「好呀」" in submit_request.system_prompt
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
    assert submit_request.llm_rewrite_metadata["reply_total_length_band"] == "complete"
    assert "semantic_style_prompt_block" not in submit_request.llm_rewrite_metadata
    assert submit_request.llm_rewrite_metadata["semantic_style_direct_candidate"] == "没救了"
    assert submit_request.llm_rewrite_metadata["semantic_style_source_example_id"] == "semantic:source:1"
    assert added["payload"]["semantic_style_source_example_id"] == "semantic:source:1"
    assert submit_request.include_session_history is True
    assert submit_request.session_history_limit == 2
    assert submit_request.include_group_ambient_history is False
    assert submit_request.hybrid_retrieval_trace["sources"] == ["memory"]


@pytest.mark.asyncio
async def test_handle_llm_chat_submits_explicit_mention_without_wait(
    monkeypatch: pytest.MonkeyPatch,
    capture_create_task: list[object],
) -> None:
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
    assert len(capture_create_task) == 1
    await capture_create_task[0]

    submit_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_llm_chat_submits_federated_alias_hard_wake(
    monkeypatch: pytest.MonkeyPatch,
    capture_create_task: list[object],
) -> None:
    from packages.llm_chat import chat_message as mod

    event = SimpleNamespace(
        to_me=False,
        _pallas_llm_alias_hard_trigger=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        raw_message="泰坦牛牛出来",
        get_plaintext=lambda: "泰坦牛牛出来",
        get_message=lambda: "泰坦牛牛出来",
        get_session_id=lambda: "group_20002_30003",
    )
    bot = SimpleNamespace(self_id="10001")

    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_llm_chat_config",
        lambda: SimpleNamespace(llm_chat_system_prompt_path="", llm_chat_min_priority=40),
    )
    monkeypatch.setattr(
        mod,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_memory_rag_enabled=False,
            llm_relationship_notes_enabled=False,
            llm_chat_enabled=True,
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
        AsyncMock(return_value=(SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})), None, None)),
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
    assert len(capture_create_task) == 1
    await capture_create_task[0]

    submit_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_llm_chat_defers_to_single_background_worker(
    monkeypatch: pytest.MonkeyPatch,
    capture_create_task: list[object],
) -> None:
    from packages.llm_chat import chat_message as mod
    from pallas.product.llm.config import LlmConfig

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        reply=None,
        raw_message="[CQ:at,qq=10001] 在吗",
        get_plaintext=lambda: "在吗",
        get_message=lambda: "[CQ:at,qq=10001] 在吗",
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
    submit_mock = AsyncMock()
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)

    await mod.handle_llm_chat(bot, event)

    assert len(capture_create_task) == 1
    submit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_llm_chat_background_worker_submits_expected_meta(
    monkeypatch: pytest.MonkeyPatch,
    capture_create_task: list[object],
) -> None:
    from packages.llm_chat import chat_message as mod
    from pallas.product.llm.config import LlmConfig

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        reply=None,
        raw_message="[CQ:at,qq=10001] 牛牛晚上好",
        get_plaintext=lambda: "牛牛晚上好",
        get_message=lambda: "[CQ:at,qq=10001] 牛牛晚上好",
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
    monkeypatch.setattr(mod, "load_recent_bot_plain_replies", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod, "resolve_login_nickname", AsyncMock(return_value=""))
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
        "pallas.product.llm.repeater_semantic_style.resolve_cached_semantic_style",
        lambda *_args, **_kwargs: SimpleNamespace(
            style_anchor="",
            matched_examples=[],
            direct_candidate=None,
            source_example_id=None,
            prompt_block="",
        ),
    )
    monkeypatch.setattr(mod.TaskManager, "add_task", AsyncMock())
    monkeypatch.setattr(mod, "maybe_auto_save_episode", AsyncMock())
    submit_mock = AsyncMock(return_value=SimpleNamespace(ok=True, task_id="ai-task-1", status="queued"))
    monkeypatch.setattr(mod, "submit_chat_task", submit_mock)

    await mod.handle_llm_chat(bot, event)
    assert len(capture_create_task) == 1
    await capture_create_task[0]

    submit_mock.assert_awaited_once()
    request = submit_mock.await_args.args[0]
    assert request.task == "llm_chat"
    assert request.session_id == "group_20002_30003"
    assert request.bot_id == 10001
    assert request.group_id == 20002
    assert request.user_id == 30003
    assert request.user_text == "牛牛晚上好"
    assert request.priority == "explicit"


@pytest.mark.asyncio
async def test_handle_llm_chat_coalesces_second_rapid_message(
    monkeypatch: pytest.MonkeyPatch,
    capture_create_task: list[object],
) -> None:
    from packages.llm_chat import chat_message as mod
    from pallas.product.llm.config import LlmConfig

    def make_event() -> SimpleNamespace:
        return SimpleNamespace(
            to_me=True,
            self_id="10001",
            group_id=20002,
            user_id=30003,
            message_id=40004,
            time=123456,
            reply=None,
            raw_message="[CQ:at,qq=10001] 在吗",
            get_plaintext=lambda: "在吗",
            get_message=lambda: "[CQ:at,qq=10001] 在吗",
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
    recorded: list[str] = []
    monkeypatch.setattr(mod, "record_bot_llm_task", lambda _task, event: recorded.append(event))

    await mod.handle_llm_chat(bot, make_event())
    await mod.handle_llm_chat(bot, make_event())

    assert len(capture_create_task) == 1
    assert recorded.count("background_enqueued") == 1
    assert recorded.count("background_coalesced") == 1


@pytest.mark.asyncio
async def test_handle_llm_chat_merged_pending_text_reaches_background_worker(
    monkeypatch: pytest.MonkeyPatch,
    capture_create_task: list[object],
) -> None:
    from packages.llm_chat import chat_message as mod
    from pallas.product.llm.chat_queue import finish_chat_turn
    from pallas.product.llm.config import LlmConfig

    def make_event(plain: str) -> SimpleNamespace:
        return SimpleNamespace(
            to_me=True,
            self_id="10001",
            group_id=20002,
            user_id=30003,
            message_id=40004,
            time=123456,
            reply=None,
            raw_message=f"[CQ:at,qq=10001] {plain}",
            get_plaintext=lambda p=plain: p,
            get_message=lambda p=plain: f"[CQ:at,qq=10001] {p}",
            get_session_id=lambda: "group_20002_30003",
        )

    bot = SimpleNamespace(self_id="10001")
    worker_kwargs: list[dict[str, object]] = []

    async def fake_prepare_and_submit(**kwargs: object) -> None:
        worker_kwargs.append(kwargs)

    monkeypatch.setattr(mod, "prepare_and_submit_llm_chat_turn", fake_prepare_and_submit)
    monkeypatch.setattr(mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_llm_chat_config",
        lambda: SimpleNamespace(llm_chat_system_prompt_path="", llm_chat_min_priority=40),
    )
    monkeypatch.setattr(mod, "get_llm_config", lambda: LlmConfig(llm_chat_enabled=True))

    await mod.handle_llm_chat(bot, make_event("在吗"))
    await mod.handle_llm_chat(bot, make_event("现在几点"))
    assert len(capture_create_task) == 1
    assert len(worker_kwargs) == 0

    finish_chat_turn(10001, 20002, 30003)
    await mod.handle_llm_chat(bot, make_event("好的"))
    assert len(capture_create_task) == 2
    await capture_create_task[1]

    assert worker_kwargs[-1]["plain"] == "现在几点\n好的"


@pytest.mark.asyncio
async def test_worker_force_quotes_deferred_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message as mod
    from pallas.product.llm.reply_target_candidates import clear_reply_target_candidates

    clear_reply_target_candidates()

    event = SimpleNamespace(
        to_me=True,
        self_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        time=123456,
        reply=None,
        raw_message="[CQ:at,qq=10001] 被延迟的那句",
        get_plaintext=lambda: "被延迟的那句",
        get_message=lambda: "[CQ:at,qq=10001] 被延迟的那句",
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
        lambda: SimpleNamespace(llm_chat_system_prompt_path="", llm_chat_min_priority=40),
    )
    monkeypatch.setattr(
        mod,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_memory_rag_enabled=False,
            llm_relationship_notes_enabled=False,
            llm_chat_enabled=True,
            llm_chat_cooldown_sec=3,
            llm_chat_queue_merge=False,
            llm_speak_followup_enabled=False,
            llm_speak_followup_window_sec=30,
            llm_speak_followup_max_total_sec=120,
            llm_speak_perception_enabled=False,
        ),
    )
    monkeypatch.setattr(
        mod,
        "build_persona_llm_context",
        AsyncMock(return_value=(SimpleNamespace(system="sys", metadata=SimpleNamespace(persona={})), None, None)),
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
    monkeypatch.setattr(mod.TaskManager, "add_task", fake_add_task)
    monkeypatch.setattr(
        mod,
        "submit_chat_task",
        AsyncMock(return_value=SimpleNamespace(ok=True, task_id="ai-task-1", status="queued")),
    )

    await mod.prepare_and_submit_llm_chat_turn(
        bot=bot,
        event=event,
        msg="[CQ:at,qq=10001] 被延迟的那句",
        plain="被延迟的那句",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        is_to_me=True,
        speak_trigger="to_me",
        llm_cfg=mod.get_llm_config(),
        chat_cfg=mod.get_llm_chat_config(),
        force_quote_message_id=40003,
    )

    payload = added["payload"]
    assert payload["reply_delivery_style"] == "QUOTE"
    assert payload["reply_to_message_id"] == 40003
    assert 40003 in payload["reply_candidate_ids"]
