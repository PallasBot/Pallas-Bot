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


# 同 Provider 内换下一把密钥；400 等业务错误不换
API_KEY_FAILOVER_STATUSES = frozenset({401, 403, 429, 502, 503})


def should_failover_api_key(exc: BaseException) -> bool:
    return isinstance(exc, LlmProviderError) and exc.status in API_KEY_FAILOVER_STATUSES


def mask_api_key_hint(key: str) -> str:
    text = str(key or "").strip()
    if len(text) <= 4:
        return "****"
    return f"…{text[-4:]}"


def host_from_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        host = (urlparse(raw).hostname or "").strip()
    except Exception:
        return ""
    return host


def format_provider_http_error(status: int, body: str = "", *, limit: int = 200) -> str:
    """统一 HTTP 错误文案，保留 524 等状态码与短正文。"""
    detail = " ".join(str(body or "").split())
    if len(detail) > limit:
        detail = detail[: limit - 1] + "…"
    if detail:
        return f"HTTP {int(status)}: {detail}"
    return f"HTTP {int(status)}"


def format_provider_transport_error(exc: BaseException, *, url: str = "") -> str:
    """传输层失败：类型名 + host，避免 toast 只剩含糊「不可达」。"""
    host = host_from_url(url)
    name = type(exc).__name__
    if isinstance(exc, httpx.TimeoutException):
        label = "连接超时" if "Connect" in name else "请求超时"
    elif isinstance(exc, httpx.ConnectError):
        label = "连接失败"
    elif isinstance(exc, httpx.HTTPError):
        label = "网络错误"
    else:
        label = name or "请求失败"
    brief = " ".join(str(exc).split())
    if len(brief) > 160:
        brief = brief[:159] + "…"
    parts = [label]
    if host:
        parts.append(host)
    if brief and brief.lower() not in {label.lower(), name.lower()}:
        parts.append(brief)
    return " · ".join(parts)


def raise_provider_http_error(response: httpx.Response) -> None:
    raise LlmProviderError(
        format_provider_http_error(response.status_code, response.text or ""),
        status=response.status_code,
    ) from None


def endpoint_api_keys(endpoint: Any, *, fallback: str = "") -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for item in getattr(endpoint, "api_keys", ()) or ():
        key = str(item or "").strip()
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    if keys:
        return keys
    primary = str(getattr(endpoint, "api_key", "") or "").strip() or str(fallback or "").strip()
    return [primary] if primary else [""]


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


def tools_for_responses_api(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Chat Completions 嵌套 function → Responses 扁平 name/parameters。

    Responses 默认倾向 strict；我们 schema 未必合规，显式 ``strict: false``。
    """
    if not tools:
        return None
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        typ = str(tool.get("type") or "").strip().lower()
        nested = tool.get("function") if isinstance(tool.get("function"), dict) else None
        if typ == "function" and nested is not None:
            flat: dict[str, Any] = {
                "type": "function",
                "name": str(nested.get("name") or "").strip(),
                "description": str(nested.get("description") or ""),
                "parameters": nested.get("parameters")
                if isinstance(nested.get("parameters"), dict)
                else {"type": "object", "properties": {}},
            }
            if "strict" in nested:
                flat["strict"] = bool(nested.get("strict"))
            else:
                flat["strict"] = False
            out.append(flat)
            continue
        if typ == "function" and str(tool.get("name") or "").strip():
            flat = dict(tool)
            flat.setdefault("strict", False)
            out.append(flat)
            continue
        out.append(tool)
    return out


def _append_responses_reasoning_item(input_items: list[dict[str, Any]], message: dict[str, Any]) -> None:
    reasoning = message.get("reasoning_content")
    if not isinstance(reasoning, str) or not reasoning.strip():
        return
    input_items.append({
        "type": "reasoning",
        "content": [{"type": "reasoning_text", "text": reasoning.strip()}],
    })


ANTHROPIC_EFFORT_BUDGET_TOKENS: dict[str, int] = {
    "minimal": 1024,
    "low": 1024,
    "medium": 4096,
    "high": 8192,
    "xhigh": 16384,
    "enable": 4096,
}


def _map_deepseek_effort_level(effort: str) -> str | None:
    """DeepSeek 档位：low/high/max（Responses 与 Chat 的 reasoning_effort 共用）。"""
    mapped = "high" if effort == "xhigh" else effort
    if mapped == "medium":
        mapped = "high"
    if mapped == "minimal":
        mapped = "low"
    if mapped == "max":
        return "max"
    if mapped in {"low", "high"}:
        return mapped
    return None


def apply_model_effort_to_payload(
    payload: dict[str, Any],
    options: dict[str, Any],
    *,
    model: str,
    request_method: str = "chat_completions",
) -> None:
    """把 Provider model_effort 映射到 Chat Completions / Responses / Anthropic 字段。"""
    effort = str(options.get("model_effort") or options.get("reasoning_effort") or "").strip().lower()
    model_name = str(model or "").strip().lower()
    method = str(request_method or "").strip().lower() or "chat_completions"
    is_responses = method == "responses"
    is_anthropic = method == "anthropic_messages"

    def disable_deepseek_thinking() -> None:
        if is_responses:
            payload["reasoning"] = {"effort": "none"}
            payload.pop("thinking", None)
            payload.pop("reasoning_effort", None)
        else:
            payload["thinking"] = {"type": "disabled"}
            payload.pop("reasoning_effort", None)

    if is_anthropic:
        if not effort or effort == "disable":
            return
        budget = ANTHROPIC_EFFORT_BUDGET_TOKENS.get(effort)
        if budget is None:
            return
        payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        max_tokens = int(payload.get("max_tokens") or 0)
        if max_tokens <= budget:
            payload["max_tokens"] = budget + 1024
        return

    # DeepSeek：默认关思考；显式开启/档位可与 tools 同开（须回传 reasoning_content）。
    if model_name.startswith("deepseek"):
        if not effort or effort == "disable":
            disable_deepseek_thinking()
            return
        if effort == "enable":
            if is_responses:
                # 不写 reasoning.none，交给厂商默认思考强度
                payload.pop("reasoning", None)
                payload.pop("thinking", None)
                payload.pop("reasoning_effort", None)
            else:
                payload["thinking"] = {"type": "enabled"}
                payload.pop("reasoning_effort", None)
            return
        level = _map_deepseek_effort_level(effort)
        if level is None:
            disable_deepseek_thinking()
            return
        if is_responses:
            payload["reasoning"] = {"effort": level}
            payload.pop("thinking", None)
            payload.pop("reasoning_effort", None)
            return
        payload["thinking"] = {"type": "enabled"}
        # Chat：reasoning_effort 用 low/high；max 按文档可传，兼容端未知时退到 high
        payload["reasoning_effort"] = level if level in {"low", "high", "max"} else "high"
        return

    if not effort or effort == "enable":
        return
    if effort == "disable":
        if is_responses:
            payload["reasoning"] = {"effort": "none"}
            payload.pop("reasoning_effort", None)
        return

    mapped = "high" if effort == "xhigh" else effort
    if is_responses:
        if mapped in {"minimal", "low", "medium", "high", "max", "none", "xhigh"}:
            payload["reasoning"] = {"effort": "high" if mapped == "xhigh" else mapped}
            payload.pop("reasoning_effort", None)
        return
    if mapped in {"minimal", "low", "medium", "high", "xhigh"}:
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
    provider_id: str | None = None,
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
            provider_id=str(provider_id or ""),
        )

    from pallas.product.llm.providers_store import resolve_endpoint_candidates_for_task

    candidates = resolve_endpoint_candidates_for_task(task)
    if candidates:
        last_error: LlmProviderError | httpx.TransportError | None = None
        for index, endpoint in enumerate(candidates):
            use_model = explicit_model if (explicit_model and index == 0) else endpoint.model
            use_method = method if request_method else endpoint.request_method
            fallback_key = str(c.llm_api_key or "").strip()
            keys = endpoint_api_keys(endpoint, fallback=fallback_key)
            key_failed_over = False
            for key_index, use_key in enumerate(keys):
                try:
                    return await _post_provider_chat(
                        messages,
                        base_url=endpoint.base_url,
                        api_key=use_key,
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
                    if should_failover_api_key(exc) and key_index + 1 < len(keys):
                        key_failed_over = True
                        logger.warning(
                            "llm api key failed, trying next key: provider={} model={} key={} err={}",
                            endpoint.provider_id,
                            use_model,
                            mask_api_key_hint(use_key),
                            exc,
                        )
                        continue
                    break
                except httpx.TransportError as exc:
                    last_error = exc
                    break
            if index + 1 >= len(candidates):
                break
            logger.warning(
                "llm provider failed, trying fallback: provider={} model={} key_failover={} err={}",
                endpoint.provider_id,
                use_model,
                key_failed_over,
                last_error,
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
            _append_responses_reasoning_item(input_items, item)
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
            if role == "assistant":
                _append_responses_reasoning_item(input_items, item)
            input_items.append({"role": role, "content": content if content is not None else ""})

    payload: dict[str, Any] = {"model": model, "input": input_items}
    if instructions:
        payload["instructions"] = instructions
    responses_tools = tools_for_responses_api(tools)
    if responses_tools:
        payload["tools"] = responses_tools
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
    apply_model_effort_to_payload(payload, options, model=model, request_method="responses")
    return payload


def parse_responses_message(data: dict[str, Any]) -> dict[str, Any]:
    texts: list[str] = []
    reasoning_texts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            typ = str(item.get("type") or "").strip().lower()
            if typ == "reasoning":
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        part_type = str(part.get("type") or "").strip().lower()
                        if part_type in {"reasoning_text", "text", "summary_text"}:
                            text = str(part.get("text") or "").strip()
                            if text:
                                reasoning_texts.append(text)
                elif isinstance(content, str) and content.strip():
                    reasoning_texts.append(content.strip())
                continue
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
    if reasoning_texts:
        message["reasoning_content"] = "\n".join(reasoning_texts).strip()
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
    apply_model_effort_to_payload(payload, options, model=model, request_method="anthropic_messages")
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
        raise LlmProviderError(format_provider_transport_error(exc, url=url)) from exc
    if response.status_code != 200:
        raise_provider_http_error(response)
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
        raise LlmProviderError(format_provider_transport_error(exc, url=url)) from exc
    if response.status_code != 200:
        raise_provider_http_error(response)
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
        raise LlmProviderError(format_provider_transport_error(exc, url=url)) from exc
    if response.status_code != 200:
        raise_provider_http_error(response)
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
