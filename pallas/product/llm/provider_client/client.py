"""Provider 上游主链路：消息补全与请求后处理。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import httpx
from nonebot import logger

from pallas.product.llm import provider_client as _repo

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# 同一 Provider 的 model 在 tool_choice=required 下不支持（如思考模式）时，记录该 (provider, model) 键，
# 后续请求自动降级为 auto。集中在此子模块持有，供 cache 清理与判断函数引用同一对象。
_required_tool_choice_incompatible: set[tuple[str, str]] = set()

ANTHROPIC_VERSION = "2023-06-01"


def clear_tool_choice_compatibility_cache() -> None:
    _required_tool_choice_incompatible.clear()


def _tool_choice_compatibility_key(provider_id: str, base_url: str, model: str) -> tuple[str, str]:
    provider = str(provider_id or "").strip() or _repo.host_from_url(base_url)
    return provider.lower(), str(model or "").strip().lower()


def _required_tool_choice_is_incompatible(exc: BaseException) -> bool:
    if not isinstance(exc, _repo.LlmProviderError) or exc.status != 400:
        return False
    detail = str(exc).lower()
    return "tool_choice" in detail and any(
        marker in detail for marker in ("does not support", "not support", "unsupported", "invalid_parameter")
    )


def _provider_response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        # Raise outside the handler so the decoder exception cannot retain its body as context.
        pass
    raise _repo.LlmProviderError("invalid provider payload", failure_class="invalid_payload") from None


def _parse_chat_completions_sse(response: httpx.Response) -> dict[str, Any]:
    body = getattr(response, "text", None)
    if not isinstance(body, str):
        content = getattr(response, "content", b"")
        body = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else ""

    message: dict[str, Any] = {"role": "assistant", "content": ""}
    tool_calls: dict[int, dict[str, Any]] = {}
    usage: Any = None
    has_usage = False
    finish_reason: str | None = None
    data_lines: list[str] = []
    done = False

    def dispatch() -> None:
        nonlocal usage, has_usage, finish_reason, done
        if not data_lines or done:
            data_lines.clear()
            return
        raw = "\n".join(data_lines)
        data_lines.clear()
        if raw.strip() == "[DONE]":
            done = True
            return
        try:
            chunk = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            _raise_provider_output_error("invalid_payload")
        if not isinstance(chunk, dict) or "error" in chunk:
            _raise_provider_output_error("invalid_payload")
        if "usage" in chunk:
            usage = chunk["usage"]
            has_usage = True
        choices = chunk.get("choices", [])
        if not isinstance(choices, list):
            _raise_provider_output_error("invalid_payload")
        for choice in choices:
            if not isinstance(choice, dict):
                _raise_provider_output_error("invalid_payload")
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                _raise_provider_output_error("invalid_payload")
            content = delta.get("content")
            if content is not None:
                if not isinstance(content, str):
                    _raise_provider_output_error("invalid_payload")
                message["content"] += content
            for reasoning in (delta.get("reasoning_content"), delta.get("reasoning")):
                if reasoning is not None:
                    if not isinstance(reasoning, str):
                        _raise_provider_output_error("invalid_payload")
                    message["reasoning_content"] = message.get("reasoning_content", "") + reasoning
            refusal = delta.get("refusal", choice.get("refusal"))
            if refusal is not None:
                if not isinstance(refusal, str):
                    _raise_provider_output_error("invalid_payload")
                message["refusal"] = message.get("refusal", "") + refusal
            if choice.get("finish_reason") is not None:
                finish_reason = choice["finish_reason"]
            fragments = delta.get("tool_calls", [])
            if not isinstance(fragments, list):
                _raise_provider_output_error("invalid_payload")
            for fragment in fragments:
                if not isinstance(fragment, dict):
                    _raise_provider_output_error("invalid_payload")
                index = fragment.get("index")
                if not isinstance(index, int) or isinstance(index, bool):
                    _raise_provider_output_error("invalid_payload")
                call = tool_calls.setdefault(index, {"id": "", "type": "function", "name": "", "arguments": ""})
                call_id = fragment.get("id")
                if call_id is not None:
                    if not isinstance(call_id, str):
                        _raise_provider_output_error("invalid_payload")
                    call["id"] += call_id
                call_type = fragment.get("type")
                if call_type is not None and call_type != "function":
                    _raise_provider_output_error("invalid_payload")
                function = fragment.get("function") or {}
                if not isinstance(function, dict):
                    _raise_provider_output_error("invalid_payload")
                for key in ("name", "arguments"):
                    value = function.get(key)
                    if value is not None:
                        if not isinstance(value, str):
                            _raise_provider_output_error("invalid_payload")
                        call[key] += value

    for line in body.splitlines():
        if not line:
            dispatch()
            if done:
                break
        elif line.startswith(":"):
            continue
        elif line.startswith("event:") and line[6:].strip() == "error":
            _raise_provider_output_error("invalid_payload")
        elif line.startswith("data:"):
            value = line[5:]
            data_lines.append(value.removeprefix(" "))
    if not done:
        dispatch()
    if not done:
        _raise_provider_output_error("invalid_payload")

    if tool_calls:
        if finish_reason == "length":
            _raise_provider_output_error("incomplete_token_limit")
        assembled_calls = []
        for index in sorted(tool_calls):
            call = tool_calls[index]
            if not call["id"].strip() or not call["name"].strip():
                _raise_provider_output_error("invalid_payload")
            try:
                arguments = json.loads(call["arguments"])
            except (json.JSONDecodeError, TypeError):
                _raise_provider_output_error("invalid_payload")
            if not isinstance(arguments, dict):
                _raise_provider_output_error("invalid_payload")
            assembled_calls.append({
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": call["arguments"]},
            })
        message["tool_calls"] = assembled_calls

    data: dict[str, Any] = {"choices": [{"index": 0, "message": message, "finish_reason": finish_reason}]}
    if has_usage:
        data["usage"] = usage
    return data


def _provider_response_is_refusal(method: str, data: dict[str, Any], message_obj: dict[str, Any]) -> bool:
    if method == "responses":
        output = data.get("output")
        for item in output if isinstance(output, list) else []:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").strip().lower() == "refusal":
                return True
            content = item.get("content")
            if isinstance(content, list) and any(
                isinstance(part, dict) and str(part.get("type") or "").strip().lower() == "refusal" for part in content
            ):
                return True
        return False
    if method == "chat_completions":
        choices = data.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        finish_reason = str(choice.get("finish_reason") or "").strip().lower()
        return bool(str(message.get("refusal") or "").strip()) or finish_reason == "content_filter"
    if method == "anthropic_messages":
        content = data.get("content")
        return (
            str(data.get("stop_reason") or "").strip().lower() == "refusal"
            or isinstance(content, list)
            and any(isinstance(block, dict) and str(block.get("type") or "").lower() == "refusal" for block in content)
        )
    done_reason = str(data.get("done_reason") or "").strip().lower()
    return bool(str(message_obj.get("refusal") or "").strip()) or done_reason in {"refusal", "content_filter"}


def _provider_empty_completion_failure_class(method: str, data: dict[str, Any]) -> str | None:
    if method == "responses":
        status = str(data.get("status") or "").strip().lower()
        if status == "incomplete":
            details = data.get("incomplete_details")
            reason = details.get("reason") if isinstance(details, dict) else None
            if reason == "max_output_tokens":
                return "incomplete_token_limit"
            return "incomplete" if reason is None else "unknown"
        return "unknown" if status and status != "completed" else None
    if method == "chat_completions":
        choices = data.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        finish_reason = str(choice.get("finish_reason") or "").strip().lower()
        if finish_reason == "length":
            return "incomplete_token_limit"
        return "unknown" if finish_reason and finish_reason not in {"stop", "tool_calls", "function_call"} else None
    if method == "anthropic_messages":
        stop_reason = str(data.get("stop_reason") or "").strip().lower()
        if stop_reason == "max_tokens":
            return "incomplete_token_limit"
        return "unknown" if stop_reason and stop_reason not in {"end_turn", "stop_sequence", "tool_use"} else None
    done_reason = str(data.get("done_reason") or "").strip().lower()
    if done_reason == "length":
        return "incomplete_token_limit"
    return "unknown" if done_reason and done_reason != "stop" else None


def _provider_output_failure_class(method: str, data: dict[str, Any], message_obj: dict[str, Any]) -> str | None:
    if method == "responses" and str(data.get("status") or "").strip().lower() == "failed":
        return "provider_failed"
    if _provider_response_is_refusal(method, data, message_obj):
        return "refusal"
    if str(message_obj.get("content") or "").strip() or message_obj.get("tool_calls"):
        return None
    failure_class = _provider_empty_completion_failure_class(method, data)
    if failure_class:
        return failure_class
    if str(message_obj.get("reasoning_content") or message_obj.get("reasoning") or "").strip():
        return "reasoning_only"
    if method == "responses":
        output = data.get("output")
        if isinstance(output, list) and any(
            isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "reasoning" for item in output
        ):
            return "reasoning_only"
    if method == "anthropic_messages":
        content = data.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict)
            and str(block.get("type") or "").strip().lower() in {"thinking", "redacted_thinking"}
            for block in content
        ):
            return "reasoning_only"
    return "no_output"


def _raise_provider_output_error(failure_class: str) -> None:
    messages = {
        "refusal": "provider refused output",
        "provider_failed": "provider response failed",
        "incomplete": "provider response incomplete",
        "incomplete_token_limit": "provider response incomplete",
        "invalid_payload": "invalid provider payload",
    }
    raise _repo.LlmProviderError(
        messages.get(failure_class, "empty provider content"),
        failure_class=failure_class,
    )


async def complete_chat_message(
    messages: list[dict[str, Any]],
    *,
    model: str,
    options: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    cfg: _repo.LlmConfig | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    task: str = "llm_chat",
    request_method: str | None = None,
    provider_id: str | None = None,
    prepare_candidate_messages: Callable[[list[dict[str, Any]], Any, str], Awaitable[list[dict[str, Any]]]]
    | None = None,
    telemetry_context: dict[str, str] | None = None,
    exit_gate: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    c = cfg or _repo.get_llm_config()
    from pallas.product.llm.availability import llm_calls_enabled

    if not llm_calls_enabled(c):
        raise _repo.LlmProviderError("llm plugin disabled or master switch off")
    explicit_base = str(base_url or "").strip()
    explicit_key = str(api_key or "").strip()
    explicit_model = str(model or "").strip()
    opts = options if isinstance(options, dict) else {}
    method = str(request_method or opts.get("request_method") or "chat_completions").strip().lower()
    telemetry_kwargs = {"telemetry_context": telemetry_context} if telemetry_context is not None else {}

    async def post_provider_chat(*args, **kwargs):
        if exit_gate is not None:
            await exit_gate()
        try:
            if exit_gate is not None:
                kwargs["exit_gate"] = exit_gate
            result = await _repo._post_provider_chat(*args, **kwargs)
        except Exception:
            if exit_gate is not None:
                await exit_gate()
            raise
        if exit_gate is not None:
            await exit_gate()
        return result

    if explicit_base:
        resolved_key = explicit_key or str(c.llm_api_key or "").strip()
        resolved_model = explicit_model or str(c.llm_model or "").strip()
        return await post_provider_chat(
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
            **telemetry_kwargs,
        )

    from pallas.product.llm.providers_store import resolve_endpoint_candidates_for_task

    candidates = resolve_endpoint_candidates_for_task(task)
    if candidates:
        last_error: _repo.LlmProviderError | httpx.TransportError | None = None
        for index, endpoint in enumerate(candidates):
            use_model = explicit_model if (explicit_model and index == 0) else endpoint.model
            use_method = method if request_method else endpoint.request_method
            fallback_key = str(c.llm_api_key or "").strip()
            keys = _repo.endpoint_api_keys(endpoint, fallback=fallback_key)
            key_failed_over = False
            candidate_messages = messages
            if prepare_candidate_messages is not None:
                candidate_messages = await prepare_candidate_messages(messages, endpoint, use_model)
            for key_index, use_key in enumerate(keys):
                try:
                    return await post_provider_chat(
                        candidate_messages,
                        base_url=endpoint.base_url,
                        api_key=use_key,
                        model=use_model,
                        options=opts,
                        tools=tools,
                        timeout_sec=float(c.chat_timeout_sec),
                        request_method=use_method,
                        task=task,
                        provider_id=str(getattr(endpoint, "provider_id", "") or ""),
                        **telemetry_kwargs,
                    )
                except _repo.LlmProviderError as exc:
                    last_error = exc
                    if _repo.should_failover_api_key(exc) and key_index + 1 < len(keys):
                        key_failed_over = True
                        logger.warning(
                            "LLM key failover for provider [{}], model [{}], key [{}], error [{}]",
                            endpoint.provider_id,
                            use_model,
                            _repo.mask_api_key_hint(use_key),
                            type(exc).__name__,
                        )
                        continue
                    break
                except httpx.TransportError as exc:
                    last_error = exc
                    break
            if index + 1 >= len(candidates):
                break
            logger.warning(
                "LLM provider [{}] failed for model [{}] with key failover [{}]; trying fallback after error type [{}]",
                endpoint.provider_id,
                use_model,
                key_failed_over,
                type(last_error).__name__,
            )
        assert last_error is not None
        raise last_error

    resolved_base = str(c.llm_base_url or "").strip()
    resolved_key = explicit_key or str(c.llm_api_key or "").strip()
    resolved_model = explicit_model or str(c.llm_model or "").strip()
    return await post_provider_chat(
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
        **telemetry_kwargs,
    )


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
    telemetry_context: dict[str, str] | None = None,
    exit_gate: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    exit_gate_errors: tuple[type[BaseException], ...] = ()
    if exit_gate is not None:
        from pallas.product.llm.availability import LlmChatExitGateError

        exit_gate_errors = (LlmChatExitGateError,)

    if provider_id and not _repo.provider_daily_budget_ok(provider_id):
        raise _repo.LlmProviderError(
            f"provider [{provider_id}] daily budget exhausted",
            status=429,
        )

    def with_provider_trace(
        result: dict[str, Any],
        *,
        latency_ms: int,
        retried_tool_choice: bool = False,
    ) -> dict[str, Any]:
        traced = dict(result)
        traced["_provider_trace"] = {
            "provider": provider_id or _repo.host_from_url(base_url),
            "model": model,
            "request_method": _repo.resolve_request_method(request_method, base_url),
            "latency_ms": latency_ms,
            "ok": True,
            "retried_tool_choice": retried_tool_choice,
        }
        return traced

    use_options = dict(options)
    # 调用方未显式指定思考档位时，沿用 Provider 配置的 model_effort，使「关闭思考」等设置全局生效
    if not (
        str(use_options.get("model_effort") or "").strip() or str(use_options.get("reasoning_effort") or "").strip()
    ):
        from pallas.product.llm.providers_store import find_provider, provider_model_effort

        try:
            row = find_provider(provider_id)
            effort = provider_model_effort(row, model) if row else ""
        except Exception:
            effort = ""
        if effort:
            use_options["model_effort"] = effort
    cache_key = _tool_choice_compatibility_key(provider_id, base_url, model)
    requested_tool_choice = str(use_options.get("tool_choice") or "auto").strip().lower()
    if tools and requested_tool_choice == "required" and cache_key in _required_tool_choice_incompatible:
        use_options["tool_choice"] = "auto"

    async def request(use_options: dict[str, Any]) -> dict[str, Any]:
        method = _repo.resolve_request_method(request_method, base_url)
        if method == "responses":
            return await _repo._post_responses(
                messages,
                base_url=base_url,
                api_key=api_key,
                model=model,
                options=use_options,
                tools=tools,
                timeout_sec=timeout_sec,
                task=task,
                provider_id=provider_id,
                telemetry_context=telemetry_context,
            )
        if method == "anthropic_messages":
            return await _repo._post_anthropic_messages(
                messages,
                base_url=base_url,
                api_key=api_key,
                model=model,
                options=use_options,
                tools=tools,
                timeout_sec=timeout_sec,
                task=task,
                provider_id=provider_id,
                telemetry_context=telemetry_context,
            )
        if method == "ollama_chat":
            return await _repo._post_ollama_chat(
                messages,
                base_url=base_url,
                api_key=api_key,
                model=model,
                options=use_options,
                tools=tools,
                timeout_sec=timeout_sec,
                task=task,
                provider_id=provider_id,
                telemetry_context=telemetry_context,
            )
        return await _repo._post_chat_completions(
            messages,
            base_url=base_url,
            api_key=api_key,
            model=model,
            options=use_options,
            tools=tools,
            timeout_sec=timeout_sec,
            task=task,
            provider_id=provider_id,
            telemetry_context=telemetry_context,
        )

    resolved_method = _repo.resolve_request_method(request_method, base_url)
    provider_name = provider_id or _repo.host_from_url(base_url)
    attempt = 0

    async def request_attempt(options_for_attempt: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempt
        if exit_gate is not None:
            await exit_gate()
        attempt += 1
        attempt_started = time.monotonic()
        try:
            result = await request(options_for_attempt)
        except exit_gate_errors:
            raise
        except Exception as exc:
            if isinstance(exc, httpx.PoolTimeout):
                _repo.note_llm_http_pool_timeout()
            _repo._emit_provider_attempt(
                telemetry_context=telemetry_context,
                decision="failed",
                reason="tool_choice_retry" if _required_tool_choice_is_incompatible(exc) else "provider_request",
                provider=provider_name,
                model=model,
                request_method=resolved_method,
                attempt=attempt,
                latency_ms=int((time.monotonic() - attempt_started) * 1000),
                failure_class=_repo._provider_failure_class(exc),
            )
            if exit_gate is not None:
                await exit_gate()
            raise
        _repo.note_llm_http_success()
        _repo._emit_provider_attempt(
            telemetry_context=telemetry_context,
            decision="success",
            reason="provider_request",
            provider=provider_name,
            model=model,
            request_method=resolved_method,
            attempt=attempt,
            latency_ms=int((time.monotonic() - attempt_started) * 1000),
        )
        if exit_gate is not None:
            await exit_gate()
        return result

    started = time.monotonic()
    try:
        result = await request_attempt(use_options)
    except exit_gate_errors:
        raise
    except Exception as exc:
        if tools and requested_tool_choice == "required" and _required_tool_choice_is_incompatible(exc):
            _required_tool_choice_incompatible.add(cache_key)
            retry_options = {**use_options, "tool_choice": "auto"}
            try:
                result = await request_attempt(retry_options)
            except exit_gate_errors:
                raise
            except Exception:
                pass
            else:
                latency_ms = int((time.monotonic() - started) * 1000)
                try:
                    from pallas.product.llm.provider_request_metrics import record_provider_request

                    record_provider_request(provider=provider_id, model=model, ok=True, latency_ms=latency_ms)
                except Exception:
                    pass
                return with_provider_trace(result, latency_ms=latency_ms, retried_tool_choice=True)
        latency_ms = int((time.monotonic() - started) * 1000)
        fail_cls = _repo._provider_failure_class(exc)
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
        return with_provider_trace(result, latency_ms=latency_ms)


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
    telemetry_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    model_name = str(model or "").strip()
    if not model_name:
        raise _repo.LlmProviderError("llm model not configured")
    url = _repo.anthropic_messages_url(base_url)
    payload = _repo.messages_to_anthropic_payload(messages, model=model_name, options=options, tools=tools)
    timeout = httpx.Timeout(float(timeout_sec))
    headers = _repo.anthropic_auth_headers(api_key)
    client = await _repo.get_llm_shared_httpx_client()
    response = await client.post(url, json=payload, headers=headers, timeout=timeout)
    if response.status_code != 200:
        logger.error(
            "LLM Anthropic messages request failed with status [{}], response bytes [{}]",
            response.status_code,
            len(response.content),
        )
        _repo.raise_provider_http_error(response)
    data = _provider_response_json(response)
    if not isinstance(data, dict):
        _raise_provider_output_error("invalid_payload")
    if data.get("content") is not None and not isinstance(data.get("content"), (list, str)):
        _raise_provider_output_error("invalid_payload")
    _repo._record_usage_from_payload(
        data,
        task=task,
        provider_id=provider_id,
        model=model_name,
        telemetry_context=telemetry_context,
    )
    message_obj = _repo.parse_anthropic_message(data)
    failure_class = _provider_output_failure_class("anthropic_messages", data, message_obj)
    if failure_class:
        _raise_provider_output_error(failure_class)
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
    telemetry_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    model_name = str(model or "").strip()
    if not model_name:
        raise _repo.LlmProviderError("llm model not configured")
    url = _repo.responses_url(base_url)
    payload = _repo.messages_to_responses_payload(messages, model=model_name, options=options, tools=tools)
    timeout = httpx.Timeout(float(timeout_sec))
    headers = _repo.auth_headers(api_key)
    client = await _repo.get_llm_shared_httpx_client()
    response = await client.post(url, json=payload, headers=headers, timeout=timeout)
    if response.status_code != 200:
        logger.error(
            "LLM responses request failed with status [{}], response bytes [{}]",
            response.status_code,
            len(response.content),
        )
        raise _repo.LlmProviderError(
            f"provider status {response.status_code}",
            status=response.status_code,
        )
    data = _provider_response_json(response)
    if not isinstance(data, dict):
        _raise_provider_output_error("invalid_payload")
    if data.get("output") is not None and not isinstance(data.get("output"), list):
        _raise_provider_output_error("invalid_payload")
    _repo._record_usage_from_payload(
        data,
        task=task,
        provider_id=provider_id,
        model=model_name,
        telemetry_context=telemetry_context,
    )
    message_obj = _repo.parse_responses_message(data)
    failure_class = _provider_output_failure_class("responses", data, message_obj)
    if failure_class:
        _raise_provider_output_error(failure_class)
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
    telemetry_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    model_name = str(model or "").strip()
    if not model_name:
        raise _repo.LlmProviderError("llm model not configured")
    url = _repo.chat_completions_url(base_url)
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
    }
    if provider_id == "cpa":
        payload["stream"] = True
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
    _repo.apply_model_effort_to_payload(payload, options, model=model_name)

    timeout = httpx.Timeout(float(timeout_sec))
    headers = _repo.auth_headers(api_key)
    client = await _repo.get_llm_shared_httpx_client()
    response = await client.post(url, json=payload, headers=headers, timeout=timeout)
    if response.status_code != 200:
        logger.error(
            "LLM provider request failed with status [{}], response bytes [{}]",
            response.status_code,
            len(response.content),
        )
        _repo.raise_provider_http_error(response)

    content_type = str(getattr(response, "headers", {}).get("content-type", "")).split(";", 1)[0].strip().lower()
    data = (
        _parse_chat_completions_sse(response)
        if provider_id == "cpa" and content_type == "text/event-stream"
        else _provider_response_json(response)
    )
    if not isinstance(data, dict):
        _raise_provider_output_error("invalid_payload")
    if data.get("success") is True and "choices" not in data:
        wrapped_data = data.get("data")
        if isinstance(wrapped_data, dict) and isinstance(wrapped_data.get("choices"), list):
            data = wrapped_data
    _repo._record_usage_from_payload(
        data,
        task=task,
        provider_id=provider_id,
        model=model_name,
        telemetry_context=telemetry_context,
    )
    choices = data.get("choices")
    if not isinstance(choices, list):
        _raise_provider_output_error("invalid_payload")
    if not choices:
        _raise_provider_output_error("no_output")
    if not isinstance(choices[0], dict):
        _raise_provider_output_error("invalid_payload")
    message_obj = choices[0].get("message")
    if not isinstance(message_obj, dict):
        _raise_provider_output_error("invalid_payload")
    failure_class = _provider_output_failure_class("chat_completions", data, message_obj)
    if failure_class:
        _raise_provider_output_error(failure_class)
    return message_obj


async def _post_ollama_chat(
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
    telemetry_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ollama 原生 /api/chat：思考模型内容直接回填 message.content，无 reasoning 空壳问题。"""
    model_name = str(model or "").strip()
    if not model_name:
        raise _repo.LlmProviderError("llm model not configured")
    url = _repo.ollama_chat_url(base_url)
    payload: dict[str, Any] = {"model": model_name, "messages": _ollama_messages(messages), "stream": False}
    if tools:
        payload["tools"] = tools
    options_payload: dict[str, Any] = {}
    temperature = options.get("temperature")
    if temperature is not None:
        options_payload["temperature"] = float(temperature)
    max_tokens = options.get("num_predict")
    if max_tokens is None:
        max_tokens = options.get("max_tokens")
    if max_tokens is not None:
        options_payload["num_predict"] = int(max_tokens)
    if options_payload:
        payload["options"] = options_payload
    think = _ollama_think_value(options)
    if think is not None:
        payload["think"] = think
    timeout = httpx.Timeout(float(timeout_sec))
    headers = _repo.auth_headers(api_key)
    client = await _repo.get_llm_shared_httpx_client()
    response = await client.post(url, json=payload, headers=headers, timeout=timeout)
    if response.status_code != 200:
        logger.error(
            "LLM provider request failed with status [{}], response bytes [{}]",
            response.status_code,
            len(response.content),
        )
        _repo.raise_provider_http_error(response)
    data = _provider_response_json(response)
    if not isinstance(data, dict):
        _raise_provider_output_error("invalid_payload")
    _repo._record_usage_from_payload(
        data,
        task=task,
        provider_id=provider_id,
        model=model_name,
        local=True,
        telemetry_context=telemetry_context,
    )
    message_obj = data.get("message")
    if not isinstance(message_obj, dict):
        _raise_provider_output_error("invalid_payload")
    content = message_obj.get("content")
    if content is not None and not isinstance(content, (list, str)):
        _raise_provider_output_error("invalid_payload")
    if isinstance(content, list):
        texts = [
            str(part.get("text") or "").strip()
            for part in content
            if isinstance(part, dict) and str(part.get("text") or "").strip()
        ]
        content = "\n".join(texts)
    message_obj = dict(message_obj)
    message_obj["content"] = str(content or "").strip()
    thinking = message_obj.get("thinking")
    if isinstance(thinking, str) and thinking.strip():
        message_obj["reasoning_content"] = thinking.strip()
    message_obj.pop("thinking", None)
    failure_class = _provider_output_failure_class("ollama_chat", data, message_obj)
    if failure_class:
        _raise_provider_output_error(failure_class)
    return message_obj


def _ollama_think_value(options: dict[str, Any]) -> bool | str | None:
    effort = str(options.get("model_effort") or "").strip().lower()
    if not effort or effort == "enable":
        return True if effort == "enable" else None
    if effort == "disable":
        # ollama.com 的 think: false 不关闭思考，而是把思考内容内联进 content；
        # 不传 think 让思考进独立 thinking 字段，content 保持干净。
        return None
    return {"minimal": "low", "low": "low", "medium": "medium", "high": "high", "xhigh": "max"}.get(
        effort,
    )


def _ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        row = dict(message)
        role = str(row.get("role") or "").strip().lower()
        content = row.get("content")
        if isinstance(content, list):
            texts: list[str] = []
            images: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").strip().lower()
                if part_type == "text":
                    text = str(part.get("text") or "")
                    if text:
                        texts.append(text)
                    continue
                if part_type != "image_url":
                    continue
                image_url = part.get("image_url")
                url = image_url.get("url") if isinstance(image_url, dict) else image_url
                raw_url = str(url or "")
                if raw_url.startswith("data:") and "," in raw_url:
                    images.append(raw_url.split(",", 1)[1])
            row["content"] = "\n".join(texts)
            if images:
                row["images"] = images
            else:
                row.pop("images", None)

        if role == "assistant" and isinstance(row.get("tool_calls"), list):
            tool_calls: list[dict[str, Any]] = []
            for call in row["tool_calls"]:
                if not isinstance(call, dict):
                    continue
                normalized = dict(call)
                function = dict(call.get("function") or {})
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        parsed = json.loads(arguments)
                    except json.JSONDecodeError:
                        parsed = None
                    if isinstance(parsed, dict):
                        function["arguments"] = parsed
                normalized["function"] = function
                tool_calls.append(normalized)
            row["tool_calls"] = tool_calls

        if role == "tool":
            tool_name = str(row.get("tool_name") or "").strip()
            if not tool_name and isinstance(content, str):
                try:
                    tool_name = str(json.loads(content).get("tool") or "").strip()
                except (json.JSONDecodeError, AttributeError):
                    pass
            if tool_name:
                row["tool_name"] = tool_name
            row.pop("tool_call_id", None)
        out.append(row)
    return out
