from __future__ import annotations

from .config import LlmConfig, get_llm_config


def is_llm_chat_service_enabled(cfg: LlmConfig | None = None) -> bool:
    """全局 LLM 闲聊能力总闸（酒后 chat 与随时 @ llm_chat 共用 LLM_CHAT_ENABLED）。"""
    return bool((cfg or get_llm_config()).llm_chat_enabled)
