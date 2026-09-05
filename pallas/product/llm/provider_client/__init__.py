"""LLM Provider 客户端（拆分包）。

对外保持模块路径 ``pallas.product.llm.provider_client`` 的导入面完整，
测试可继续经该命名空间打桩共享符号。
"""

from __future__ import annotations

# 从其它模块 re-export，供旧路径 `provider_client.<sym>` 保持兼容
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.provider_client.auth import (
    anthropic_auth_headers,
    auth_headers,
    endpoint_api_keys,
)
from pallas.product.llm.provider_client.budget import (
    _record_usage_from_payload,
    provider_daily_budget_ok,
)
from pallas.product.llm.provider_client.client import (
    ANTHROPIC_VERSION,
    _post_anthropic_messages,
    _post_chat_completions,
    _post_provider_chat,
    _post_responses,
    _required_tool_choice_incompatible,
    _required_tool_choice_is_incompatible,
    _tool_choice_compatibility_key,
    clear_tool_choice_compatibility_cache,
    complete_chat_message,
)
from pallas.product.llm.provider_client.errors import (
    API_KEY_FAILOVER_STATUSES,
    LlmProviderError,
    _emit_provider_attempt,
    _provider_failure_class,
    format_provider_http_error,
    format_provider_transport_error,
    host_from_url,
    mask_api_key_hint,
    raise_provider_http_error,
    should_failover_api_key,
)
from pallas.product.llm.provider_client.mapping import (
    ANTHROPIC_DEFAULT_MAX_TOKENS,
    ANTHROPIC_EFFORT_BUDGET_TOKENS,
    _append_responses_reasoning_item,
    _content_as_text,
    _map_deepseek_effort_level,
    apply_model_effort_to_payload,
    messages_to_anthropic_payload,
    messages_to_responses_payload,
    openai_tools_to_anthropic,
    parse_anthropic_message,
    parse_responses_message,
    tools_for_responses_api,
)
from pallas.product.llm.provider_client.models import (
    list_anthropic_models,
    list_ollama_tag_models,
    list_openai_compatible_models,
    parse_ollama_tags_payload,
    parse_openai_models_payload,
    probe_provider_models,
)
from pallas.product.llm.provider_client.urls import (
    _has_versioned_root,
    anthropic_messages_url,
    anthropic_models_url,
    chat_completions_url,
    is_anthropic_official_host,
    models_url,
    normalize_openai_base_url,
    ollama_tags_url,
    openai_api_root,
    resolve_request_method,
    responses_url,
)
from pallas.product.llm.shared_httpx import get_llm_shared_httpx_client
from pallas.product.llm.turn_telemetry import record_turn_event

__all__ = [
    "ANTHROPIC_DEFAULT_MAX_TOKENS",
    "ANTHROPIC_EFFORT_BUDGET_TOKENS",
    "ANTHROPIC_VERSION",
    "API_KEY_FAILOVER_STATUSES",
    "LlmConfig",
    "LlmProviderError",
    "_append_responses_reasoning_item",
    "_content_as_text",
    "_emit_provider_attempt",
    "_has_versioned_root",
    "_map_deepseek_effort_level",
    "_post_anthropic_messages",
    "_post_chat_completions",
    "_post_provider_chat",
    "_post_responses",
    "_provider_failure_class",
    "_record_usage_from_payload",
    "_required_tool_choice_incompatible",
    "_required_tool_choice_is_incompatible",
    "_tool_choice_compatibility_key",
    "anthropic_auth_headers",
    "anthropic_messages_url",
    "anthropic_models_url",
    "apply_model_effort_to_payload",
    "auth_headers",
    "chat_completions_url",
    "clear_tool_choice_compatibility_cache",
    "complete_chat_message",
    "endpoint_api_keys",
    "format_provider_http_error",
    "format_provider_transport_error",
    "get_llm_config",
    "get_llm_shared_httpx_client",
    "host_from_url",
    "is_anthropic_official_host",
    "list_anthropic_models",
    "list_ollama_tag_models",
    "list_openai_compatible_models",
    "mask_api_key_hint",
    "messages_to_anthropic_payload",
    "messages_to_responses_payload",
    "models_url",
    "normalize_openai_base_url",
    "ollama_tags_url",
    "openai_api_root",
    "openai_tools_to_anthropic",
    "parse_anthropic_message",
    "parse_ollama_tags_payload",
    "parse_openai_models_payload",
    "parse_responses_message",
    "probe_provider_models",
    "provider_daily_budget_ok",
    "raise_provider_http_error",
    "record_turn_event",
    "resolve_request_method",
    "responses_url",
    "should_failover_api_key",
    "tools_for_responses_api",
]
