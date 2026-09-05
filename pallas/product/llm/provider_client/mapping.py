"""Provider 消息 / 工具 / 思考档位在不同上游协议间的映射与解析。"""

from __future__ import annotations

import json
from typing import Any

from pallas.product.llm import provider_client as _repo

ANTHROPIC_DEFAULT_MAX_TOKENS = 8192

ANTHROPIC_EFFORT_BUDGET_TOKENS: dict[str, int] = {
    "minimal": 1024,
    "low": 1024,
    "medium": 4096,
    "high": 8192,
    "xhigh": 16384,
    "enable": 4096,
}


def _append_responses_reasoning_item(input_items: list[dict[str, Any]], message: dict[str, Any]) -> None:
    reasoning = message.get("reasoning_content")
    if not isinstance(reasoning, str) or not reasoning.strip():
        return
    input_items.append({
        "type": "reasoning",
        "content": [{"type": "reasoning_text", "text": reasoning.strip()}],
    })


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
        # 非 DeepSeek 模型（如 qwen3）默认可能开思考，required tool_choice 会被拒；同样禁用
        payload["thinking"] = {"type": "disabled"}
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


def messages_to_responses_payload(
    messages: list[dict[str, Any]],
    *,
    model: str,
    options: dict[str, Any],
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    def responses_content_parts(content: Any) -> Any:
        if not isinstance(content, list):
            return content
        parts: list[Any] = []
        for part in content:
            if not isinstance(part, dict):
                parts.append(part)
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type == "text":
                parts.append({"type": "input_text", "text": part.get("text", "")})
                continue
            if part_type == "image_url":
                image_url = part.get("image_url")
                if isinstance(image_url, dict):
                    url = image_url.get("url")
                    detail = image_url.get("detail", "auto")
                else:
                    url = image_url
                    detail = "auto"
                if url:
                    parts.append({
                        "type": "input_image",
                        "image_url": url,
                        "detail": detail,
                    })
                    continue
            parts.append(part)
        return parts

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
            _repo._append_responses_reasoning_item(input_items, item)
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
                _repo._append_responses_reasoning_item(input_items, item)
            input_items.append({
                "role": role,
                "content": responses_content_parts(content) if content is not None else "",
            })

    payload: dict[str, Any] = {"model": model, "input": input_items}
    if instructions:
        payload["instructions"] = instructions
    responses_tools = _repo.tools_for_responses_api(tools)
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
    def anthropic_content_parts(content: Any) -> Any:
        if not isinstance(content, list):
            return content
        parts: list[Any] = []
        for part in content:
            if isinstance(part, str):
                parts.append({"type": "text", "text": part})
                continue
            if not isinstance(part, dict):
                parts.append(part)
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type == "text":
                parts.append({"type": "text", "text": part.get("text", "")})
                continue
            if part_type != "image_url":
                parts.append(part)
                continue
            image_url = part.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            url = str(url or "").strip()
            if url.lower().startswith("data:"):
                header, separator, data = url.partition(",")
                media_type, _, encoding = header[5:].partition(";")
                media_type = media_type.strip().lower()
                if separator and data and media_type in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
                    if "base64" in {item.strip().lower() for item in encoding.split(";") if item}:
                        parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        })
                        continue
            elif url.lower().startswith(("http://", "https://")):
                parts.append({
                    "type": "image",
                    "source": {"type": "url", "url": url},
                })
                continue
        return parts

    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []

    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = item.get("content")
        if role == "system":
            text = _repo._content_as_text(content).strip()
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            tool_result = {
                "type": "tool_result",
                "tool_use_id": str(item.get("tool_call_id") or "").strip(),
                "content": _repo._content_as_text(content),
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
            text = _repo._content_as_text(content).strip()
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
            converted.append({
                "role": "user",
                "content": anthropic_content_parts(content) if content is not None else "",
            })

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
    anthropic_tools = _repo.openai_tools_to_anthropic(tools)
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
