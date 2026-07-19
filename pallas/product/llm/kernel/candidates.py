"""Unified candidate representation for generation and scoring."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .models import ConversationAction, GenerationStage


class CandidateSource(StrEnum):
    CORPUS = "corpus"
    SELECT = "select"
    REWRITE = "rewrite"
    STITCH = "stitch"
    GENERATE = "generate"
    DIRECT_CHAT = "direct_chat"


class ConversationCandidate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    text: str
    source: CandidateSource = CandidateSource.CORPUS
    action: ConversationAction = ConversationAction.REPLY_CORPUS
    stage: GenerationStage | None = None
    grounded: bool = True
    base_score: float = Field(default=0.0, ge=0.0)
    duplicate_key: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        source: CandidateSource,
        action: ConversationAction | None = None,
        stage: GenerationStage | None = None,
        grounded: bool = True,
        base_score: float = 0.0,
    ) -> ConversationCandidate:
        resolved_action = action or stage_to_action(stage, source)
        return cls(
            text=str(text or "").strip(),
            source=source,
            action=resolved_action,
            stage=stage,
            grounded=grounded,
            base_score=base_score,
            duplicate_key=str(text or "").strip(),
        )


def stage_to_action(stage: GenerationStage | None, source: CandidateSource) -> ConversationAction:
    if stage == GenerationStage.SELECT:
        return ConversationAction.REPLY_CORPUS
    if stage == GenerationStage.REWRITE:
        return ConversationAction.REPLY_REWRITE
    if stage == GenerationStage.STITCH:
        return ConversationAction.REPLY_STITCH
    if stage == GenerationStage.GENERATE:
        return ConversationAction.REPLY_GENERATE
    if source == CandidateSource.DIRECT_CHAT:
        return ConversationAction.REPLY_GENERATE
    return ConversationAction.REPLY_CORPUS
