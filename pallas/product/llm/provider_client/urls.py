"""Provider 上游 URL 构造 / 请求方式解析。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pallas.product.llm import provider_client as _repo


def normalize_openai_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def _has_versioned_root(base: str) -> bool:
    """末尾已是版本段（/v1、/v4 等）或 /openai，视为已带 API 版本根。"""
    return bool(re.search(r"/v\d+$", base) or base.endswith("/openai"))


def openai_api_root(base_url: str) -> str:
    """OpenAI 兼容根路径：末尾已带版本段（/v1、/v4 等）或 /openai 时不再追加 /v1。"""
    base = _repo.normalize_openai_base_url(base_url)
    if not base:
        raise _repo.LlmProviderError("llm base url not configured")
    if _has_versioned_root(base):
        return base
    return f"{base}/v1"


def chat_completions_url(base_url: str) -> str:
    return f"{_repo.openai_api_root(base_url)}/chat/completions"


def responses_url(base_url: str) -> str:
    return f"{_repo.openai_api_root(base_url)}/responses"


def models_url(base_url: str) -> str:
    return f"{_repo.openai_api_root(base_url)}/models"


def anthropic_messages_url(base_url: str) -> str:
    base = _repo.normalize_openai_base_url(base_url)
    if not base:
        raise _repo.LlmProviderError("llm base url not configured")
    if _has_versioned_root(base):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def anthropic_models_url(base_url: str) -> str:
    base = _repo.normalize_openai_base_url(base_url)
    if not base:
        raise _repo.LlmProviderError("llm base url not configured")
    if _has_versioned_root(base):
        return f"{base}/models"
    return f"{base}/v1/models"


def is_anthropic_official_host(base_url: str) -> bool:
    host = (urlparse(str(base_url or "").strip()).hostname or "").lower()
    return host == "api.anthropic.com" or host.endswith(".api.anthropic.com")


def resolve_request_method(request_method: str | None, base_url: str) -> str:
    method = str(request_method or "").strip().lower() or "chat_completions"
    if method == "anthropic_messages":
        return method
    # 官方 Anthropic 端点默认走 Messages；OpenRouter 等兼容代理仍用 chat_completions
    if method == "chat_completions" and _repo.is_anthropic_official_host(base_url):
        return "anthropic_messages"
    return method


def ollama_tags_url(base_url: str) -> str:
    base = _repo.normalize_openai_base_url(base_url)
    if not base:
        raise _repo.LlmProviderError("ollama base url not configured")
    base = base.removesuffix("/v1")
    return f"{base.rstrip('/')}/api/tags"
