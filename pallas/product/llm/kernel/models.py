"""Shared conversation kernel vocabulary for repeater and llm_chat."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ConversationPath(StrEnum):
    REPEATER_ASSIST = "repeater_assist"
    LLM_CHAT_DIRECT = "llm_chat_direct"


class ConversationAction(StrEnum):
    SKIP = "skip"
    REPLY_CORPUS = "reply_corpus"
    REPLY_REWRITE = "reply_rewrite"
    REPLY_STITCH = "reply_stitch"
    REPLY_GENERATE = "reply_generate"
    SPEAK_GENERATE = "speak_generate"


class ConversationScene(StrEnum):
    PROVOCATION = "provocation"
    BANTER = "banter"
    SMALLTALK = "smalltalk"
    VENTING = "venting"
    GROUP_THREADING = "group_threading"
    LIGHT_HELP = "light_help"
    IDLE_OPPORTUNITY = "idle_opportunity"
    HOSTED_CONTEXT = "hosted_context"


class ConversationMode(StrEnum):
    NORMAL = "normal"
    GOD = "god"
    GHOST = "ghost"


class GenerationStage(StrEnum):
    SELECT = "select"
    REWRITE = "rewrite"
    STITCH = "stitch"
    GENERATE = "generate"


class ConversationFeatureLevel(StrEnum):
    LEGACY_REPEATER = "legacy_repeater"
    REPEATER_PLUS_DECISION = "repeater_plus_decision"
    FULL_CONVERSATION_KERNEL = "full_conversation_kernel"


class DecisionConstraints(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    max_length: int = Field(default=0, ge=0)
    min_length: int = Field(default=0, ge=0)
    topic_anchor: str = ""
    disallow_drift: bool = True
    disallow_service_tone: bool = True


class DecisionTrace(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    path: ConversationPath
    scene: ConversationScene = ConversationScene.SMALLTALK
    mode: ConversationMode = ConversationMode.NORMAL
    action: ConversationAction = ConversationAction.SKIP
    stance: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    trace_reason: str = ""
    constraints: DecisionConstraints = Field(default_factory=DecisionConstraints)
    opportunity_accepted: bool = False
    generation_stages: list[str] = Field(default_factory=list)
    extra: dict[str, object] = Field(default_factory=dict)

    def to_trace_row(self) -> dict[str, object]:
        payload = self.model_dump(mode="json")
        payload["kind"] = "conversation_decision_trace"
        return payload


def normalize_conversation_mode(raw: str | None) -> ConversationMode:
    text = str(raw or "normal").strip().lower()
    if text == ConversationMode.GOD:
        return ConversationMode.GOD
    if text == ConversationMode.GHOST:
        return ConversationMode.GHOST
    return ConversationMode.NORMAL


def behavior_scene_to_conversation_scene(raw: str | ConversationScene) -> ConversationScene:
    text = str(raw or "").strip().lower()
    for item in ConversationScene:
        if item.value == text:
            return item
    return ConversationScene.SMALLTALK


def generation_stage_to_action(stage: str | GenerationStage) -> ConversationAction:
    text = str(stage or "").strip().lower()
    if text == GenerationStage.SELECT:
        return ConversationAction.REPLY_CORPUS
    if text in {GenerationStage.REWRITE, GenerationStage.STITCH}:
        return ConversationAction.REPLY_REWRITE if text == GenerationStage.REWRITE else ConversationAction.REPLY_STITCH
    if text == GenerationStage.GENERATE:
        return ConversationAction.REPLY_GENERATE
    return ConversationAction.SKIP
