from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass(frozen=True, slots=True)
class StructuredChatReply:
    """已解析的可见聊天气泡；logical_text 只用于单轮会话与学习。"""

    reply_segments: tuple[str, ...] = ()
    intent: str = ""
    mem: str = ""
    sticker_intent: str = "none"
    reasoning: str = ""
    from_json: bool = False

    @property
    def logical_text(self) -> str:
        return "\n".join(self.reply_segments)

    @property
    def reply(self) -> str:
        """兼容旧消费者的单文本视图。"""
        return self.logical_text

    @property
    def sticker(self) -> str:
        """兼容旧消费者的贴纸字段名。"""
        return self.sticker_intent

    @classmethod
    def single(cls, text: str, **kwargs: Any) -> StructuredChatReply:
        plain = str(text or "").strip()
        return cls(reply_segments=(plain,) if plain else (), **kwargs)


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
    group_timeline_images: list[dict[str, str]] = Field(default_factory=list)
    tool_metadata: dict[str, Any] | None = None
    include_session_history: bool = True
    session_history_limit: int | None = Field(default=None, ge=1)
    include_group_ambient_history: bool = True
    prepared_messages: list[ChatCompletionMessage] | None = None
    # 被引用(回复)的消息 id：用于提取引用消息里的图片并送入视觉上下文
    reply_to_message_id: int | None = None
    # 措辞相关临时提示（口癖/换风格/同句重回），插在最后一条 user 之前
    style_user_hints: list[str] = Field(default_factory=list)


class ChatSubmitResult(BaseModel):
    task_id: str = ""
    status: str = ""
    ok: bool = False


class ChatCompletionMessage(BaseModel):
    role: str
    content: str
    source_token: str = Field(default="", exclude=True)


class ChatCompletionRequest(BaseModel):
    session_id: str
    messages: list[ChatCompletionMessage]
    system: str = Field(min_length=1)
    model: str | None = None
    metadata: dict[str, str | int | None] = Field(default_factory=dict)
