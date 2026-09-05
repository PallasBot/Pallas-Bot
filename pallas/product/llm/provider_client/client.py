"""Provider 上游主链路：消息补全与请求后处理。"""

from __future__ import annotations

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
) -> dict[str, Any]:
    c = cfg or _repo.get_llm_config()
    explicit_base = str(base_url or "").strip()
    explicit_key = str(api_key or "").strip()
    explicit_model = str(model or "").strip()
    opts = options if isinstance(options, dict) else {}
    method = str(request_method or opts.get("request_method") or "chat_completions").strip().lower()
    telemetry_kwargs = {"telemetry_context": telemetry_context} if telemetry_context is not None else {}

    if explicit_base:
        resolved_key = explicit_key or str(c.llm_api_key or "").strip()
        resolved_model = explicit_model or str(c.llm_model or "").strip()
        return await _repo._post_provider_chat(
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
                    return await _repo._post_provider_chat(
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
    return await _repo._post_provider_chat(
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
) -> dict[str, Any]:
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
        attempt += 1
        attempt_started = time.monotonic()
        try:
            result = await request(options_for_attempt)
        except Exception as exc:
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
            raise
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
        return result

    started = time.monotonic()
    try:
        result = await request_attempt(use_options)
    except Exception as exc:
        if tools and requested_tool_choice == "required" and _required_tool_choice_is_incompatible(exc):
            _required_tool_choice_incompatible.add(cache_key)
            retry_options = {**use_options, "tool_choice": "auto"}
            try:
                result = await request_attempt(retry_options)
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
    data = response.json()
    if not isinstance(data, dict):
        raise _repo.LlmProviderError("invalid anthropic messages payload")
    _repo._record_usage_from_payload(
        data,
        task=task,
        provider_id=provider_id,
        model=model_name,
        telemetry_context=telemetry_context,
    )
    message_obj = _repo.parse_anthropic_message(data)
    if not str(message_obj.get("content", "") or "").strip() and not message_obj.get("tool_calls"):
        raise _repo.LlmProviderError("empty provider content")
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
    data = response.json()
    if not isinstance(data, dict):
        raise _repo.LlmProviderError("invalid responses payload")
    _repo._record_usage_from_payload(
        data,
        task=task,
        provider_id=provider_id,
        model=model_name,
        telemetry_context=telemetry_context,
    )
    message_obj = _repo.parse_responses_message(data)
    if not str(message_obj.get("content", "") or "").strip() and not message_obj.get("tool_calls"):
        raise _repo.LlmProviderError("empty provider content")
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

    data = response.json()
    if isinstance(data, dict):
        _repo._record_usage_from_payload(
            data,
            task=task,
            provider_id=provider_id,
            model=model_name,
            telemetry_context=telemetry_context,
        )
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        raise _repo.LlmProviderError("empty provider choices")
    message_obj = choices[0].get("message") if isinstance(choices[0], dict) else {}
    if not isinstance(message_obj, dict):
        raise _repo.LlmProviderError("invalid provider message")
    if not str(message_obj.get("content", "") or "").strip() and not message_obj.get("tool_calls"):
        raise _repo.LlmProviderError("empty provider content")
    return message_obj
