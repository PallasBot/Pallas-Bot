"""统一 LLM 产品层。

**Runtime**（进程内对话）：``kernel``、``delivery``、``tools``、``orchestration`` —
聊天插件经 ``runtime_api`` 导入。

**Ops**（控制台运维）：``providers_store``、``model_admin``、``webui_config``、
记忆图谱管理等 — 控制台经 ``ops_api`` 导入，聊天插件不应直接依赖。

顶层 ``__init__`` 仍暴露通用客户端与配置；细分边界见 ``runtime_api`` / ``ops_api``。
"""

import importlib
from typing import TYPE_CHECKING, Any

from .availability import is_drunk_chat_enabled, is_legacy_rwkv_drunk_chat_enabled, is_llm_chat_service_enabled
from .config import LlmConfig, clear_llm_config_cache, get_llm_config, llm_server_base_url
from .message_guard import contains_likely_prompt_injection, format_user_turn, sanitize_user_message
from .models import ChatCompletionMessage, ChatCompletionRequest, ChatSubmitRequest, ChatSubmitResult

if TYPE_CHECKING:
    from .client import build_chat_messages, delete_llm_chat_session, submit_chat_task
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
    if name in {"build_chat_messages", "delete_llm_chat_session", "submit_chat_task"}:
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
