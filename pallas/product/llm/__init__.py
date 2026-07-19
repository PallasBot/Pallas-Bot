"""统一 LLM 客户端：AI 仓调用与用户消息防注入。"""

import importlib
from typing import TYPE_CHECKING, Any

from .availability import is_drunk_chat_enabled, is_legacy_rwkv_drunk_chat_enabled, is_llm_chat_service_enabled
from .config import LlmConfig, clear_llm_config_cache, get_llm_config, llm_server_base_url
from .message_guard import contains_likely_prompt_injection, format_user_turn, sanitize_user_message
from .models import ChatCompletionMessage, ChatCompletionRequest, ChatSubmitRequest, ChatSubmitResult

if TYPE_CHECKING:
    from .client import build_chat_messages, chat_endpoint_path, delete_llm_chat_session, submit_chat_task
    from .drunk_chat_context import DrunkChatSubmitContext, build_drunk_chat_system_prompt

__all__ = [
    "ChatCompletionMessage",
    "ChatCompletionRequest",
    "ChatSubmitRequest",
    "ChatSubmitResult",
    "DrunkChatSubmitContext",
    "LlmConfig",
    "build_drunk_chat_system_prompt",
    "build_chat_messages",
    "chat_endpoint_path",
    "clear_llm_config_cache",
    "delete_llm_chat_session",
    "contains_likely_prompt_injection",
    "format_user_turn",
    "get_llm_config",
    "is_drunk_chat_enabled",
    "is_legacy_rwkv_drunk_chat_enabled",
    "is_llm_chat_service_enabled",
    "llm_server_base_url",
    "sanitize_user_message",
    "submit_chat_task",
]


def __getattr__(name: str) -> Any:
    if name in {"build_chat_messages", "chat_endpoint_path", "delete_llm_chat_session", "submit_chat_task"}:
        module = importlib.import_module(".client", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in {"DrunkChatSubmitContext", "build_drunk_chat_system_prompt"}:
        module = importlib.import_module(".drunk_chat_context", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
