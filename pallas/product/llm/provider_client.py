"""Bot 内核：OpenAI 兼容 / Anthropic Messages 客户端。"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx
from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config

ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_DEFAULT_MAX_TOKENS = 8192


class LlmProviderError(Exception):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _record_usage_from_payload(
    data: dict[str, Any],
    *,
    task: str,
    provider_id: str,
    model: str,
    local: bool = False,
) -> None:
    try:
        from pallas.product.llm.token_metrics import record_llm_token_usage
        from pallas.product.llm.token_usage import (
            usage_from_local_chat_response,
            usage_from_remote_chat_response,
        )

        if local:
            prompt, completion, cache_read, cache_write = usage_from_local_chat_response(data)
            if prompt == 0 and completion == 0:
                prompt, completion, cache_read, cache_write = usage_from_remote_chat_response(data)
        else:
            prompt, completion, cache_read, cache_write = usage_from_remote_chat_response(data)
            if prompt == 0 and completion == 0 and cache_read == 0 and cache_write == 0:
                prompt, completion, cache_read, cache_write = usage_from_local_chat_response(data)
        record_llm_token_usage(
            task=task,
            provider=provider_id or None,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
    except Exception:
        pass


def normalize_openai_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def openai_api_root(base_url: str) -> str:
    """OpenAI 兼容根路径：已以 /v1 或 /openai 结尾时不再追加 /v1。"""
    base = normalize_openai_base_url(base_url)
    if not base:
        raise LlmProviderError("llm base url not configured")
    if base.endswith(("/v1", "/openai")):
        return base
    return f"{base}/v1"


def chat_completions_url(base_url: str) -> str:
    return f"{openai_api_root(base_url)}/chat/completions"


def responses_url(base_url: str) -> str:
    return f"{openai_api_root(base_url)}/responses"


def models_url(base_url: str) -> str:
    return f"{openai_api_root(base_url)}/models"


def anthropic_messages_url(base_url: str) -> str:
    base = normalize_openai_base_url(base_url)
    if not base:
        raise LlmProviderError("llm base url not configured")
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def anthropic_models_url(base_url: str) -> str:
    base = normalize_openai_base_url(base_url)
    if not base:
        raise LlmProviderError("llm base url not configured")
    if base.endswith("/v1"):
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
    if method == "chat_completions" and is_anthropic_official_host(base_url):
        return "anthropic_messages"
    return method


def auth_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def anthropic_auth_headers(api_key: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    key = str(api_key or "").strip()
    if key:
        headers["x-api-key"] = key
    return headers


def apply_model_effort_to_payload(payload: dict[str, Any], options: dict[str, Any], *, model: str) -> None:
    """把 Provider model_effort 映射到常见 OpenAI 兼容字段。"""
    effort = str(options.get("model_effort") or options.get("reasoning_effort") or "").strip().lower()
    model_name = str(model or "").strip().lower()
    # DeepSeek thinking 多轮须回传 reasoning_content；会话/tool loop 未存该字段时会 400。
    # 带 tools，或未显式指定 effort 档位时，默认关闭 thinking。
    if model_name.startswith("deepseek"):
        if payload.get("tools") or not effort or effort in {"enable", "disable"}:
            payload["thinking"] = {"type": "disabled"}
            return
    elif not effort or effort == "enable":
        return
    elif effort == "disable":
        return
    mapped = "high" if effort == "xhigh" else effort
    if mapped in {"minimal", "low", "medium", "high"}:
        payload["reasoning_effort"] = mapped


async def complete_chat_message(
    messages: list[dict[str, Any]],
    *,
    model: str,
    options: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    cfg: LlmConfig | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    task: str = "llm_chat",
    request_method: str | None = None,
) -> dict[str, Any]:
    c = cfg or get_llm_config()
    explicit_base = str(base_url or "").strip()
    explicit_key = str(api_key or "").strip()
    explicit_model = str(model or "").strip()
    opts = options if isinstance(options, dict) else {}
    method = str(request_method or opts.get("request_method") or "chat_completions").strip().lower()

    if explicit_base:
        resolved_key = explicit_key or str(c.llm_api_key or "").strip()
        resolved_model = explicit_model or str(c.llm_model or "").strip()
        return await _post_provider_chat(
            messages,
            base_url=explicit_base,
            api_key=resolved_key,
            model=resolved_model,
            options=opts,
            tools=tools,
            timeout_sec=float(c.chat_timeout_sec),
            request_method=method,
            task=task,
            provider_id="",
        )

    from pallas.product.llm.providers_store import resolve_endpoint_candidates_for_task

    candidates = resolve_endpoint_candidates_for_task(task)
    if candidates:
        last_error: LlmProviderError | None = None
        for index, endpoint in enumerate(candidates):
            use_model = explicit_model if (explicit_model and index == 0) else endpoint.model
            use_method = method if request_method else endpoint.request_method
            try:
                return await _post_provider_chat(
                    messages,
                    base_url=endpoint.base_url,
                    api_key=endpoint.api_key or str(c.llm_api_key or "").strip(),
                    model=use_model,
                    options=opts,
                    tools=tools,
                    timeout_sec=float(c.chat_timeout_sec),
                    request_method=use_method,
                    task=task,
                    provider_id=str(getattr(endpoint, "provider_id", "") or ""),
                )
            except LlmProviderError as exc:
                last_error = exc
                if index + 1 >= len(candidates):
                    break
                logger.warning(
                    "llm provider failed, trying fallback: provider={} model={} err={}",
                    endpoint.provider_id,
                    use_model,
                    exc,
                )
        assert last_error is not None
        raise last_error

    resolved_base = str(c.llm_base_url or "").strip()
    resolved_key = explicit_key or str(c.llm_api_key or "").strip()
    resolved_model = explicit_model or str(c.llm_model or "").strip()
    return await _post_provider_chat(
        messages,
        base_url=resolved_base,
        api_key=resolved_key,
        model=resolved_model,
        options=opts,
        tools=tools,
        timeout_sec=float(c.chat_timeout_sec),
        request_method=method,
        task=task,
        provider_id="",
    )


def messages_to_responses_payload(
    messages: list[dict[str, Any]],
    *,
    model: str,
    options: dict[str, Any],
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    instructions = ""
    input_items: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = item.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                instructions = f"{instructions}\n{content}".strip() if instructions else content.strip()
            continue
        if role == "tool":
            input_items.append({
                "type": "function_call_output",
                "call_id": str(item.get("tool_call_id") or "").strip(),
                "output": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            })
            continue
        if role == "assistant" and item.get("tool_calls"):
            for call in item.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                args = fn.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args or {}, ensure_ascii=False)
                input_items.append({
                    "type": "function_call",
                    "call_id": str(call.get("id") or "").strip(),
                    "name": str(fn.get("name") or "").strip(),
                    "arguments": args,
                })
            if isinstance(content, str) and content.strip():
                input_items.append({"role": "assistant", "content": content})
            continue
        if role in {"user", "assistant"}:
            input_items.append({"role": role, "content": content if content is not None else ""})

    payload: dict[str, Any] = {"model": model, "input": input_items}
    if instructions:
        payload["instructions"] = instructions
    if tools:
        payload["tools"] = tools
        choice = str(options.get("tool_choice") or "auto").strip() or "auto"
        payload["tool_choice"] = choice
    temperature = options.get("temperature")
    if temperature is not None:
        payload["temperature"] = float(temperature)
    max_tokens = options.get("num_predict")
    if max_tokens is None:
        max_tokens = options.get("max_tokens")
    if max_tokens is not None:
        payload["max_output_tokens"] = int(max_tokens)
    apply_model_effort_to_payload(payload, options, model=model)
    return payload


def parse_responses_message(data: dict[str, Any]) -> dict[str, Any]:
    texts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            typ = str(item.get("type") or "").strip().lower()
            if typ == "message":
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        part_type = str(part.get("type") or "").strip().lower()
                        if part_type in {"output_text", "text"}:
                            text = str(part.get("text") or "").strip()
                            if text:
                                texts.append(text)
                elif isinstance(content, str) and content.strip():
                    texts.append(content.strip())
            elif typ == "function_call":
                args = item.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args or {}, ensure_ascii=False)
                tool_calls.append({
                    "id": str(item.get("call_id") or item.get("id") or "").strip(),
                    "type": "function",
                    "function": {
                        "name": str(item.get("name") or "").strip(),
                        "arguments": args,
                    },
                })
    output_text = str(data.get("output_text") or "").strip()
    if output_text:
        texts.append(output_text)
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(texts).strip(),
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _content_as_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def openai_tools_to_anthropic(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not tools:
        return []
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if "input_schema" in tool and tool.get("name"):
            schema = tool.get("input_schema")
            out.append({
                "name": str(tool.get("name") or "").strip(),
                "description": str(tool.get("description") or ""),
                "input_schema": schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
            })
            continue
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else None
        if fn is None and str(tool.get("type") or "").strip().lower() == "function":
            fn = tool
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        params = fn.get("parameters")
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
        out.append({
            "name": name,
            "description": str(fn.get("description") or ""),
            "input_schema": params,
        })
    return out


def messages_to_anthropic_payload(
    messages: list[dict[str, Any]],
    *,
    model: str,
    options: dict[str, Any],
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []

    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = item.get("content")
        if role == "system":
            text = _content_as_text(content).strip()
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            tool_result = {
                "type": "tool_result",
                "tool_use_id": str(item.get("tool_call_id") or "").strip(),
                "content": _content_as_text(content),
            }
            if converted and converted[-1].get("role") == "user" and isinstance(converted[-1].get("content"), list):
                prev = converted[-1]["content"]
                if prev and isinstance(prev[0], dict) and prev[0].get("type") == "tool_result":
                    prev.append(tool_result)
                    continue
            converted.append({"role": "user", "content": [tool_result]})
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = _content_as_text(content).strip()
            if text:
                blocks.append({"type": "text", "text": text})
            for call in item.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                args_raw = fn.get("arguments")
                if isinstance(args_raw, str):
                    try:
                        args_obj = json.loads(args_raw) if args_raw.strip() else {}
                    except json.JSONDecodeError:
                        args_obj = {}
                elif isinstance(args_raw, dict):
                    args_obj = args_raw
                else:
                    args_obj = {}
                blocks.append({
                    "type": "tool_use",
                    "id": str(call.get("id") or "").strip(),
                    "name": str(fn.get("name") or "").strip(),
                    "input": args_obj if isinstance(args_obj, dict) else {},
                })
            if blocks:
                converted.append({"role": "assistant", "content": blocks})
            continue
        if role == "user":
            converted.append({"role": "user", "content": content if content is not None else ""})

    max_tokens = options.get("num_predict")
    if max_tokens is None:
        max_tokens = options.get("max_tokens")
    if max_tokens is None:
        max_tokens = ANTHROPIC_DEFAULT_MAX_TOKENS

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": int(max_tokens),
        "messages": converted,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    anthropic_tools = openai_tools_to_anthropic(tools)
    if anthropic_tools:
        payload["tools"] = anthropic_tools
    temperature = options.get("temperature")
    if temperature is not None:
        payload["temperature"] = float(temperature)
    return payload


def parse_anthropic_message(data: dict[str, Any]) -> dict[str, Any]:
    texts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    content = data.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            typ = str(block.get("type") or "").strip().lower()
            if typ == "text":
                text = str(block.get("text") or "").strip()
                if text:
                    texts.append(text)
            elif typ == "tool_use":
                args = block.get("input")
                if not isinstance(args, dict):
                    args = {}
                tool_calls.append({
                    "id": str(block.get("id") or "").strip(),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name") or "").strip(),
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                })
    elif isinstance(content, str) and content.strip():
        texts.append(content.strip())
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(texts).strip(),
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


async def _post_provider_chat(
    messages: list[dict[str, Any]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    options: dict[str, Any],
    tools: list[dict[str, Any]] | None,
    timeout_sec: float,
    request_method: str = "chat_completions",
    task: str = "llm_chat",
    provider_id: str = "",
) -> dict[str, Any]:
    import time

    started = time.monotonic()
    try:
        method = resolve_request_method(request_method, base_url)
        if method == "responses":
            result = await _post_responses(
                messages,
                base_url=base_url,
                api_key=api_key,
                model=model,
                options=options,
                tools=tools,
                timeout_sec=timeout_sec,
                task=task,
                provider_id=provider_id,
            )
        elif method == "anthropic_messages":
            result = await _post_anthropic_messages(
                messages,
                base_url=base_url,
                api_key=api_key,
                model=model,
                options=options,
                tools=tools,
                timeout_sec=timeout_sec,
                task=task,
                provider_id=provider_id,
            )
        else:
            result = await _post_chat_completions(
                messages,
                base_url=base_url,
                api_key=api_key,
                model=model,
                options=options,
                tools=tools,
                timeout_sec=timeout_sec,
                task=task,
                provider_id=provider_id,
            )
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        fail_cls = "provider_error"
        if isinstance(exc, LlmProviderError) and exc.status is not None:
            fail_cls = f"http_{exc.status}"
        elif isinstance(exc, TimeoutError):
            fail_cls = "timeout"
        try:
            from pallas.product.llm.provider_request_metrics import record_provider_request

            record_provider_request(
                provider=provider_id,
                model=model,
                ok=False,
                latency_ms=latency_ms,
                failure_class=fail_cls,
            )
        except Exception:
            pass
        raise
    else:
        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            from pallas.product.llm.provider_request_metrics import record_provider_request

            record_provider_request(
                provider=provider_id,
                model=model,
                ok=True,
                latency_ms=latency_ms,
            )
        except Exception:
            pass
        return result


async def _post_anthropic_messages(
    messages: list[dict[str, Any]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    options: dict[str, Any],
    tools: list[dict[str, Any]] | None,
    timeout_sec: float,
    task: str = "llm_chat",
    provider_id: str = "",
) -> dict[str, Any]:
    model_name = str(model or "").strip()
    if not model_name:
        raise LlmProviderError("llm model not configured")
    url = anthropic_messages_url(base_url)
    payload = messages_to_anthropic_payload(messages, model=model_name, options=options, tools=tools)
    timeout = httpx.Timeout(float(timeout_sec))
    headers = anthropic_auth_headers(api_key)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        logger.error(
            "llm anthropic messages failed: status={} body={}",
            response.status_code,
            (response.text or "")[:500],
        )
        raise LlmProviderError(
            f"provider status {response.status_code}",
            status=response.status_code,
        )
    data = response.json()
    if not isinstance(data, dict):
        raise LlmProviderError("invalid anthropic messages payload")
    _record_usage_from_payload(data, task=task, provider_id=provider_id, model=model_name)
    message_obj = parse_anthropic_message(data)
    if not str(message_obj.get("content", "") or "").strip() and not message_obj.get("tool_calls"):
        raise LlmProviderError("empty provider content")
    return message_obj


async def _post_responses(
    messages: list[dict[str, Any]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    options: dict[str, Any],
    tools: list[dict[str, Any]] | None,
    timeout_sec: float,
    task: str = "llm_chat",
    provider_id: str = "",
) -> dict[str, Any]:
    model_name = str(model or "").strip()
    if not model_name:
        raise LlmProviderError("llm model not configured")
    url = responses_url(base_url)
    payload = messages_to_responses_payload(messages, model=model_name, options=options, tools=tools)
    timeout = httpx.Timeout(float(timeout_sec))
    headers = auth_headers(api_key)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        logger.error(
            "llm responses failed: status={} body={}",
            response.status_code,
            (response.text or "")[:500],
        )
        raise LlmProviderError(
            f"provider status {response.status_code}",
            status=response.status_code,
        )
    data = response.json()
    if not isinstance(data, dict):
        raise LlmProviderError("invalid responses payload")
    _record_usage_from_payload(data, task=task, provider_id=provider_id, model=model_name)
    message_obj = parse_responses_message(data)
    if not str(message_obj.get("content", "") or "").strip() and not message_obj.get("tool_calls"):
        raise LlmProviderError("empty provider content")
    return message_obj


async def _post_chat_completions(
    messages: list[dict[str, Any]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    options: dict[str, Any],
    tools: list[dict[str, Any]] | None,
    timeout_sec: float,
    task: str = "llm_chat",
    provider_id: str = "",
) -> dict[str, Any]:
    model_name = str(model or "").strip()
    if not model_name:
        raise LlmProviderError("llm model not configured")
    url = chat_completions_url(base_url)
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        choice = str(options.get("tool_choice") or "auto").strip() or "auto"
        payload["tool_choice"] = choice
    temperature = options.get("temperature")
    if temperature is not None:
        payload["temperature"] = float(temperature)
    max_tokens = options.get("num_predict")
    if max_tokens is None:
        max_tokens = options.get("max_tokens")
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    apply_model_effort_to_payload(payload, options, model=model_name)

    timeout = httpx.Timeout(float(timeout_sec))
    headers = auth_headers(api_key)
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
    if isinstance(data, dict):
        _record_usage_from_payload(data, task=task, provider_id=provider_id, model=model_name)
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
    request_method: str | None = None,
) -> list[str]:
    method = resolve_request_method(request_method, base_url)
    if method == "anthropic_messages":
        return await list_anthropic_models(base_url, api_key, timeout_sec=timeout_sec)
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


async def list_anthropic_models(
    base_url: str,
    api_key: str = "",
    *,
    timeout_sec: float = 15.0,
) -> list[str]:
    url = anthropic_models_url(base_url)
    headers = anthropic_auth_headers(api_key)
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
        raise LlmProviderError("invalid anthropic models response") from exc
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
    base = str(c.llm_base_url or "").strip()
    key = str(c.llm_api_key or "").strip()
    if not base:
        from pallas.product.llm.providers_store import resolve_endpoint_for_task

        endpoint = resolve_endpoint_for_task("llm_chat")
        if endpoint is not None:
            base = endpoint.base_url
            key = key or endpoint.api_key
    try:
        url = models_url(base)
    except LlmProviderError as exc:
        return {"ok": False, "url": "", "error": str(exc)}
    headers = auth_headers(key)
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
