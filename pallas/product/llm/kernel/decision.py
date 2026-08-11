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
    ConversationScene,
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
    elif has_grounded_candidate:
        action = ConversationAction.REPLY_CORPUS
        trace_reason = "corpus_reply"
        stages = []
    else:
        action = ConversationAction.SKIP
        trace_reason = "no_candidate"
        stages = []

    constraints = build_mode_constraints(ctx.reply_mode, scene=ctx.scene)
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
    constraints = build_mode_constraints(ConversationMode.NORMAL, scene=ctx.scene, direct_chat=True)
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


def build_mode_constraints(
    mode: ConversationMode,
    *,
    scene: ConversationScene | str | None = None,
    direct_chat: bool = False,
) -> DecisionConstraints:
    from pallas.product.llm.scene_style import resolve_scene_style_constraints

    return resolve_scene_style_constraints(scene, mode, direct_chat=direct_chat)
