from __future__ import annotations

from .config import LlmConfig, get_llm_config


def is_llm_chat_service_enabled(cfg: LlmConfig | None = None) -> bool:
    """智能对话总开关。"""
    return bool((cfg or get_llm_config()).llm_chat_enabled)
