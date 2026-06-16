from __future__ import annotations

from .config import LlmConfig, get_llm_config, resolve_legacy_rwkv_drunk_chat_enabled


def is_llm_chat_service_enabled(cfg: LlmConfig | None = None) -> bool:
    """智能对话总开关（酒后 LLM 与随时 @ 共用）。"""
    return bool((cfg or get_llm_config()).llm_chat_enabled)


def is_legacy_rwkv_drunk_chat_enabled() -> bool:
    """遗留酒后 RWKV 开关（未配置 LLM_CHAT_ENABLED 时的 CHAT_ENABLE）。"""
    return resolve_legacy_rwkv_drunk_chat_enabled()


def is_drunk_chat_enabled(cfg: LlmConfig | None = None) -> bool:
    """酒后聊天是否可用（LLM 总闸或遗留 RWKV）。"""
    return is_llm_chat_service_enabled(cfg) or is_legacy_rwkv_drunk_chat_enabled()
