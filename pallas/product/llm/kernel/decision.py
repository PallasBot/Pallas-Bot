"""Rule-first conversation decision service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from .context import ConversationContext

from .models import (
    ConversationAction,
    ConversationFeatureLevel,
    ConversationMode,
    ConversationPath,
    DecisionConstraints,
    DecisionTrace,
    GenerationStage,
)


class DecisionResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    action: ConversationAction
    trace: DecisionTrace
    opportunity_accepted: bool = False
    generation_stages: list[GenerationStage] = Field(default_factory=list)
    agent_stages: list[str] = Field(default_factory=list)


def resolve_direct_chat_action() -> ConversationAction:
    return ConversationAction.REPLY_GENERATE


def plan_direct_chat_stages(*, tools_enabled: bool) -> list[str]:
    if tools_enabled:
        return ["plan", "tool_loop", GenerationStage.GENERATE.value]
    return [GenerationStage.GENERATE.value]


def decide_repeater_action(
    ctx: ConversationContext,
    *,
    llm_enabled: bool,
    select_enabled: bool,
    polish_enabled: bool,
    polish_lite_enabled: bool,
    has_grounded_candidate: bool,
    opportunity_accepted: bool,
    opportunity_trace_extra: dict[str, Any] | None = None,
    feature_level: ConversationFeatureLevel = ConversationFeatureLevel.FULL_CONVERSATION_KERNEL,
) -> DecisionResult:
    trace_extra = dict(opportunity_trace_extra or {})

    if feature_level == ConversationFeatureLevel.LEGACY_REPEATER and not opportunity_accepted:
        action = ConversationAction.SKIP
        trace_reason = "legacy_repeater_opportunity_rejected"
        stages: list[GenerationStage] = []
    elif not opportunity_accepted:
        action = ConversationAction.SKIP
        trace_reason = "opportunity_rejected"
        stages = []
    elif llm_enabled and feature_level == ConversationFeatureLevel.FULL_CONVERSATION_KERNEL:
        stages = plan_generation_stages(
            has_candidate_pool=ctx.has_candidate_pool,
            candidate_pool_size=ctx.candidate_pool_size,
            has_grounded_candidate=has_grounded_candidate,
            select_enabled=select_enabled,
            polish_enabled=polish_enabled,
            polish_lite_enabled=polish_lite_enabled,
        )
        action = stages_to_primary_action(stages)
        trace_reason = "llm_pipeline_planned"
    elif has_grounded_candidate:
        action = ConversationAction.REPLY_CORPUS
        trace_reason = "corpus_reply"
        stages = []
    else:
        action = ConversationAction.SKIP
        trace_reason = "no_candidate"
        stages = []

    constraints = build_mode_constraints(ctx.reply_mode)
    trace = DecisionTrace(
        path=ConversationPath.REPEATER_ASSIST,
        scene=ctx.scene,
        mode=ctx.reply_mode,
        action=action,
        confidence=1.0 if opportunity_accepted else 0.0,
        trace_reason=trace_reason,
        constraints=constraints,
        opportunity_accepted=opportunity_accepted,
        generation_stages=[stage.value for stage in stages],
        extra=trace_extra,
    )
    return DecisionResult(
        action=action,
        trace=trace,
        opportunity_accepted=opportunity_accepted,
        generation_stages=stages,
        agent_stages=[stage.value for stage in stages],
    )


def decide_direct_chat_action(
    ctx: ConversationContext,
    *,
    feature_level: ConversationFeatureLevel = ConversationFeatureLevel.FULL_CONVERSATION_KERNEL,
    tools_enabled: bool = False,
) -> DecisionResult:
    action = resolve_direct_chat_action()
    if feature_level == ConversationFeatureLevel.LEGACY_REPEATER:
        action = ConversationAction.REPLY_GENERATE
    agent_stages = plan_direct_chat_stages(tools_enabled=tools_enabled)
    constraints = build_mode_constraints(ConversationMode.NORMAL, direct_chat=True)
    trace = DecisionTrace(
        path=ConversationPath.LLM_CHAT_DIRECT,
        scene=ctx.scene,
        mode=ConversationMode.NORMAL,
        action=action,
        confidence=1.0,
        trace_reason="direct_chat_agent_loop_planned" if tools_enabled else "direct_chat_forced_reply",
        constraints=constraints,
        opportunity_accepted=True,
        generation_stages=agent_stages,
        extra={"tools_enabled": tools_enabled},
    )
    return DecisionResult(
        action=action,
        trace=trace,
        opportunity_accepted=True,
        generation_stages=[GenerationStage.GENERATE],
        agent_stages=agent_stages,
    )


def plan_generation_stages(
    *,
    has_candidate_pool: bool,
    candidate_pool_size: int,
    has_grounded_candidate: bool,
    select_enabled: bool,
    polish_enabled: bool,
    polish_lite_enabled: bool,
) -> list[GenerationStage]:
    stages: list[GenerationStage] = []
    if candidate_pool_size >= 2 and select_enabled:
        stages.append(GenerationStage.SELECT)
    if has_grounded_candidate and (polish_enabled or polish_lite_enabled):
        stages.append(GenerationStage.REWRITE)
    if candidate_pool_size >= 2:
        stages.append(GenerationStage.STITCH)
    if not stages or not (has_candidate_pool or has_grounded_candidate):
        return [GenerationStage.GENERATE]
    if GenerationStage.GENERATE not in stages:
        stages.append(GenerationStage.GENERATE)
    return stages


def stages_to_primary_action(stages: list[GenerationStage]) -> ConversationAction:
    if not stages:
        return ConversationAction.SKIP
    first = stages[0]
    if first == GenerationStage.SELECT:
        return ConversationAction.REPLY_CORPUS
    if first == GenerationStage.REWRITE:
        return ConversationAction.REPLY_REWRITE
    if first == GenerationStage.STITCH:
        return ConversationAction.REPLY_STITCH
    return ConversationAction.REPLY_GENERATE


def build_mode_constraints(mode: ConversationMode, *, direct_chat: bool = False) -> DecisionConstraints:
    if direct_chat:
        return DecisionConstraints(max_length=120, min_length=1, disallow_drift=False)
    if mode == ConversationMode.GHOST:
        return DecisionConstraints(max_length=18, min_length=1, disallow_drift=True)
    if mode == ConversationMode.GOD:
        return DecisionConstraints(max_length=48, min_length=2, disallow_drift=True)
    return DecisionConstraints(max_length=36, min_length=1, disallow_drift=True)
