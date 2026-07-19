from __future__ import annotations

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.kernel import (
    ConversationAction,
    ConversationContext,
    ConversationFeatureLevel,
    ConversationMode,
    ConversationPath,
    ConversationScene,
    GenerationStage,
    behavior_scene_to_conversation_scene,
    build_repeater_generation_plan,
    decide_direct_chat_action,
    decide_repeater_action,
    plan_generation_stages,
    resolve_conversation_feature_level,
    resolve_memory_read_policy,
)
from pallas.product.llm.kernel.models import DecisionTrace
from pallas.product.persona.affect_kernel import build_persona_affect_contract


def test_behavior_scene_maps_to_conversation_scene() -> None:
    scene = behavior_scene_to_conversation_scene("banter")
    assert scene == ConversationScene.BANTER


def test_decision_trace_serializes_kernel_fields() -> None:
    trace = DecisionTrace(
        path=ConversationPath.REPEATER_ASSIST,
        scene=ConversationScene.BANTER,
        action=ConversationAction.REPLY_CORPUS,
        trace_reason="corpus_reply",
        opportunity_accepted=True,
        generation_stages=["select", "rewrite"],
    )
    row = trace.to_trace_row()
    assert row["kind"] == "conversation_decision_trace"
    assert row["action"] == "reply_corpus"
    assert row["scene"] == "banter"


def test_plan_generation_stages_orders_grounded_before_generate() -> None:
    stages = plan_generation_stages(
        has_candidate_pool=True,
        candidate_pool_size=3,
        has_grounded_candidate=True,
        select_enabled=True,
        polish_enabled=True,
        polish_lite_enabled=False,
    )
    assert stages[0] == GenerationStage.SELECT
    assert stages[-1] == GenerationStage.GENERATE


def test_decide_repeater_action_skips_when_opportunity_rejected() -> None:
    ctx = ConversationContext.for_repeater(
        plain_text="嗯",
        group_id=1,
        bot_id=2,
        user_id=3,
        reply_mode="normal",
        unique_users=1,
        recent_message_count=1,
        has_candidate_pool=False,
        candidate_pool_size=0,
        candidate_style_score=0.0,
        has_recent_back_and_forth=False,
        bot_recently_replied=False,
    )
    result = decide_repeater_action(
        ctx,
        llm_enabled=True,
        select_enabled=True,
        polish_enabled=True,
        polish_lite_enabled=False,
        has_grounded_candidate=False,
        opportunity_accepted=False,
        feature_level=ConversationFeatureLevel.FULL_CONVERSATION_KERNEL,
    )
    assert result.action == ConversationAction.SKIP
    assert result.opportunity_accepted is False


def test_decide_direct_chat_action_forces_reply_generate() -> None:
    ctx = ConversationContext.for_direct_chat(
        plain_text="@牛牛 你好",
        group_id=100,
        bot_id=1,
        user_id=2,
        scene=ConversationScene.SMALLTALK,
    )
    result = decide_direct_chat_action(ctx)
    assert result.action == ConversationAction.REPLY_GENERATE
    assert result.trace.path == ConversationPath.LLM_CHAT_DIRECT
    assert result.agent_stages == ["generate"]
    assert result.trace.generation_stages == ["generate"]


def test_decide_direct_chat_action_plans_agent_loop_when_tools_enabled() -> None:
    ctx = ConversationContext.for_direct_chat(
        plain_text="@牛牛 帮我查一下能天使技能",
        group_id=100,
        bot_id=1,
        user_id=2,
        scene=ConversationScene.LIGHT_HELP,
    )
    result = decide_direct_chat_action(ctx, tools_enabled=True)
    assert result.action == ConversationAction.REPLY_GENERATE
    assert result.agent_stages == ["plan", "tool_loop", "generate"]
    assert result.trace.generation_stages == ["plan", "tool_loop", "generate"]
    assert result.trace.trace_reason == "direct_chat_agent_loop_planned"


def test_resolve_conversation_feature_level_legacy_when_llm_disabled(monkeypatch) -> None:
    clear_llm_config_cache()
    monkeypatch.delenv("CONVERSATION_FEATURE_LEVEL", raising=False)
    monkeypatch.delenv("LLM_CHAT_ENABLED", raising=False)
    level = resolve_conversation_feature_level(LlmConfig(llm_chat_enabled=False))
    assert level == ConversationFeatureLevel.LEGACY_REPEATER


def test_resolve_conversation_feature_level_explicit_override(monkeypatch) -> None:
    clear_llm_config_cache()
    level = resolve_conversation_feature_level(
        LlmConfig(
            llm_chat_enabled=False,
            conversation_feature_level="full_conversation_kernel",
        )
    )
    assert level == ConversationFeatureLevel.FULL_CONVERSATION_KERNEL


def test_memory_read_policy_disables_behavioral_learning_by_default() -> None:
    policy = resolve_memory_read_policy(LlmConfig(llm_chat_enabled=True, llm_repeater_bias_enabled=False))
    assert policy.allow_behavioral_learning is False
    assert policy.allow_writeback is False


def test_build_repeater_generation_plan_exposes_stage_names() -> None:
    plan = build_repeater_generation_plan(
        path=ConversationPath.REPEATER_ASSIST,
        stages=[GenerationStage.SELECT, GenerationStage.GENERATE],
        scene=ConversationScene.SMALLTALK,
        mode=ConversationMode.NORMAL,
        user_text="测试",
        candidate_pool=["一", "二"],
        candidate_text="一",
        fallback_text="一",
    )
    assert plan.stage_names == ["select", "generate"]


def test_persona_affect_contract_prefers_short_length_for_short_persona() -> None:
    from pallas.product.persona.model import ResolvedPersona

    contract = build_persona_affect_contract(ResolvedPersona(length_pref="short"))
    assert contract.preferred_length_max <= 16
