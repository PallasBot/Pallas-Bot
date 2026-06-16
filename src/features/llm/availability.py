from __future__ import annotations

from .config import LlmConfig, get_llm_config


def is_llm_chat_service_enabled(cfg: LlmConfig | None = None) -> bool:
    """全局 LLM 闲聊能力总闸（默认开；显式 LLM_CHAT_ENABLED / 遗留 OLLAMA_ENABLE 可关）。"""
    return bool((cfg or get_llm_config()).llm_chat_enabled)
