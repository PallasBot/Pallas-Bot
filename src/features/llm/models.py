from __future__ import annotations

from pydantic import BaseModel, Field


class ChatSubmitRequest(BaseModel):
    request_id: str
    session_id: str
    user_text: str
    system_prompt: str = Field(min_length=1)
    model: str | None = None
    bot_id: int | None = None
    group_id: int | None = None
    user_id: int | None = None
    mode: str = "normal"
    token_count: int | None = None
    temperature: float | None = None
    task: str | None = None


class ChatSubmitResult(BaseModel):
    task_id: str = ""
    status: str = ""
    ok: bool = False


class ChatCompletionMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    session_id: str
    messages: list[ChatCompletionMessage]
    system: str = Field(min_length=1)
    model: str | None = None
    metadata: dict[str, str | int | None] = Field(default_factory=dict)
