"""Bot 内核：OpenAI 兼容 chat.completions 客户端。"""

from __future__ import annotations

from typing import Any

import httpx
from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config


class LlmProviderError(Exception):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def normalize_openai_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def chat_completions_url(base_url: str) -> str:
    base = normalize_openai_base_url(base_url)
    if not base:
        raise LlmProviderError("llm base url not configured")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def models_url(base_url: str) -> str:
    base = normalize_openai_base_url(base_url)
    if not base:
        raise LlmProviderError("llm base url not configured")
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def auth_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


async def complete_chat_message(
    messages: list[dict[str, Any]],
    *,
    model: str,
    options: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    cfg: LlmConfig | None = None,
) -> dict[str, Any]:
    c = cfg or get_llm_config()
    model_name = str(model or c.llm_model or "").strip()
    if not model_name:
        raise LlmProviderError("llm model not configured")
    url = chat_completions_url(c.llm_base_url)
    opts = options if isinstance(options, dict) else {}
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    temperature = opts.get("temperature")
    if temperature is not None:
        payload["temperature"] = float(temperature)
    max_tokens = opts.get("num_predict")
    if max_tokens is None:
        max_tokens = opts.get("max_tokens")
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    timeout = httpx.Timeout(float(c.chat_timeout_sec))
    headers = auth_headers(c.llm_api_key)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        logger.error(
            "llm provider failed: status={} body={}",
            response.status_code,
            (response.text or "")[:500],
        )
        raise LlmProviderError(
            f"provider status {response.status_code}",
            status=response.status_code,
        )

    data = response.json()
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        raise LlmProviderError("empty provider choices")
    message_obj = choices[0].get("message") if isinstance(choices[0], dict) else {}
    if not isinstance(message_obj, dict):
        raise LlmProviderError("invalid provider message")
    if not str(message_obj.get("content", "") or "").strip() and not message_obj.get("tool_calls"):
        raise LlmProviderError("empty provider content")
    return message_obj


def parse_openai_models_payload(payload: Any) -> list[str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        mid = item.get("id") if isinstance(item, dict) else None
        if isinstance(mid, str) and mid.strip():
            out.append(mid.strip())
    return out


def parse_ollama_tags_payload(payload: Any) -> list[str]:
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    out: list[str] = []
    for item in models:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def ollama_tags_url(base_url: str) -> str:
    base = normalize_openai_base_url(base_url)
    if not base:
        raise LlmProviderError("ollama base url not configured")
    base = base.removesuffix("/v1")
    return f"{base.rstrip('/')}/api/tags"


async def list_openai_compatible_models(
    base_url: str,
    api_key: str = "",
    *,
    timeout_sec: float = 15.0,
) -> list[str]:
    url = models_url(base_url)
    headers = auth_headers(api_key)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
            response = await client.get(url, headers=headers)
    except Exception as exc:
        raise LlmProviderError(str(exc)) from exc
    if response.status_code != 200:
        detail = (response.text or "")[:200]
        raise LlmProviderError(
            f"HTTP {response.status_code}" + (f": {detail}" if detail else ""),
            status=response.status_code,
        )
    try:
        payload = response.json()
    except Exception as exc:
        raise LlmProviderError("invalid models response") from exc
    return parse_openai_models_payload(payload)


async def list_ollama_tag_models(
    base_url: str,
    *,
    timeout_sec: float = 15.0,
) -> list[str]:
    url = ollama_tags_url(base_url)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
            response = await client.get(url)
    except Exception as exc:
        raise LlmProviderError(str(exc)) from exc
    if response.status_code != 200:
        raise LlmProviderError(f"HTTP {response.status_code}", status=response.status_code)
    try:
        payload = response.json()
    except Exception as exc:
        raise LlmProviderError("invalid ollama tags response") from exc
    return parse_ollama_tags_payload(payload)


async def probe_provider_models(*, timeout_sec: float = 3.0, cfg: LlmConfig | None = None) -> dict[str, Any]:
    c = cfg or get_llm_config()
    try:
        url = models_url(c.llm_base_url)
    except LlmProviderError as exc:
        return {"ok": False, "url": "", "error": str(exc)}
    headers = auth_headers(c.llm_api_key)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
            response = await client.get(url, headers=headers)
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    ok = response.status_code == 200
    return {
        "ok": ok,
        "url": url,
        "status_code": response.status_code,
        "error": "" if ok else f"HTTP {response.status_code}",
    }
