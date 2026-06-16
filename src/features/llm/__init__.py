"""统一 LLM 客户端：AI 仓调用与用户消息防注入。"""

from .availability import is_drunk_chat_enabled, is_legacy_rwkv_drunk_chat_enabled, is_llm_chat_service_enabled
from .client import build_chat_messages, chat_endpoint_path, delete_llm_chat_session, submit_chat_task
from .config import LlmConfig, clear_llm_config_cache, get_llm_config, llm_server_base_url
from .message_guard import contains_likely_prompt_injection, format_user_turn, sanitize_user_message
from .models import ChatCompletionMessage, ChatCompletionRequest, ChatSubmitRequest, ChatSubmitResult
from .tools import registry as tools_registry  # noqa: F401 — 注册内置 tools

__all__ = [
    "ChatCompletionMessage",
    "ChatCompletionRequest",
    "ChatSubmitRequest",
    "ChatSubmitResult",
    "LlmConfig",
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
