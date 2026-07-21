from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

LlmChatRole = Literal["user", "assistant"]
ALLOWED_ROLES = frozenset({"user", "assistant"})


class LlmChatTurn(BaseModel):
    role: LlmChatRole
    content: str
    user_id: int
    created_at: int


class LlmSessionScope(BaseModel):
    bot_id: int
    group_id: int = 0
    user_id: int | None = None


class LlmHistorySessionSummary(BaseModel):
    session_key: str
    bot_id: int
    group_id: int
    user_id: int
    turn_count: int
    first_created_at: int
    last_created_at: int
    last_role: LlmChatRole
    last_content: str


class LlmHistorySessionDetail(BaseModel):
    session: LlmHistorySessionSummary
    turns: list[LlmChatTurn]
    behavior_runs: list[dict[str, Any]] = Field(default_factory=list)
    feedback_entries: list[dict[str, Any]] = Field(default_factory=list)


def normalize_group_scope(group_id: int | None) -> int:
    return int(group_id) if group_id is not None else 0


def is_private_scope(group_id: int | None) -> bool:
    return normalize_group_scope(group_id) == 0
