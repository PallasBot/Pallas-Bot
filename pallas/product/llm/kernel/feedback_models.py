"""Feedback models for llm_chat -> repeater learning."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeedbackBiasSnapshot(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    count: int = 0
    top_replies: list[str] = Field(default_factory=list)
    matched_replies: list[str] = Field(default_factory=list)
    semantic_matched_replies: list[str] = Field(default_factory=list)
    penalized_replies: list[str] = Field(default_factory=list)
    scenes: list[str] = Field(default_factory=list)
    learning_stats: dict[str, int | float] = Field(default_factory=dict)
