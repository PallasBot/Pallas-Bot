from __future__ import annotations

from typing import Any

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
    scene_tier: str = "weak"
    priority: str = "repeater_weak"
    knowledge_retrieval_trace: dict[str, Any] | None = None
    hybrid_retrieval_trace: dict[str, Any] | None = None
    llm_rewrite_metadata: dict[str, Any] | None = None
    tool_metadata: dict[str, Any] | None = None
    include_session_history: bool = True
    # 措辞相关临时提示（口癖/换风格/同句重回），插在最后一条 user 之前
    style_user_hints: list[str] = Field(default_factory=list)


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
