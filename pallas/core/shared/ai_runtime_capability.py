from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AiCapabilityGroup = Literal["dialogue", "media", "automation", "extension"]
AiCapabilityId = Literal[
    "llm.chat",
    "image.generate",
    "media.sing",
    "automation.maa",
    "ai_extension.runtime",
]
AiRuntimeType = Literal["llm", "image", "media", "automation", "extension"]
AiRequestMode = Literal["sync", "async", "hybrid"]
AiProviderType = Literal[
    "openai_compatible",
    "ollama",
    "image_gateway",
    "local_worker",
    "remote_media_service",
    "bot_internal",
]


@dataclass(frozen=True, slots=True)
class AiRuntimeCapability:
    capability_id: AiCapabilityId
    capability_group: AiCapabilityGroup
    label: str
    runtime_type: AiRuntimeType
    request_mode: AiRequestMode
    supported_provider_types: tuple[AiProviderType, ...]
    supports_task_mode: bool
    supports_sync_mode: bool
    supports_callback: bool
    supports_stream: bool
    default_timeout_sec: int
    default_queue: str | None = None


LLM_CHAT = AiRuntimeCapability(
    "llm.chat",
    "dialogue",
    "对话运行时",
    "llm",
    "sync",
    ("ollama", "openai_compatible"),
    supports_task_mode=False,
    supports_sync_mode=True,
    supports_callback=False,
    supports_stream=True,
    default_timeout_sec=60,
)
IMAGE_GENERATE = AiRuntimeCapability(
    "image.generate",
    "media",
    "绘图运行时",
    "image",
    "hybrid",
    ("image_gateway",),
    supports_task_mode=True,
    supports_sync_mode=True,
    supports_callback=False,
    supports_stream=False,
    default_timeout_sec=180,
    default_queue="image",
)
MEDIA_SING = AiRuntimeCapability(
    "media.sing",
    "media",
    "点歌运行时",
    "media",
    "async",
    ("local_worker", "remote_media_service"),
    supports_task_mode=True,
    supports_sync_mode=False,
    supports_callback=True,
    supports_stream=False,
    default_timeout_sec=300,
    default_queue="media",
)
AUTOMATION_MAA = AiRuntimeCapability(
    "automation.maa",
    "automation",
    "MAA 自动化运行时",
    "automation",
    "async",
    ("bot_internal",),
    supports_task_mode=True,
    supports_sync_mode=False,
    supports_callback=True,
    supports_stream=False,
    default_timeout_sec=120,
    default_queue="automation",
)
AI_EXTENSION_RUNTIME = AiRuntimeCapability(
    "ai_extension.runtime",
    "extension",
    "AI 扩展运行时",
    "extension",
    "sync",
    ("remote_media_service", "openai_compatible"),
    supports_task_mode=False,
    supports_sync_mode=True,
    supports_callback=False,
    supports_stream=False,
    default_timeout_sec=15,
)
