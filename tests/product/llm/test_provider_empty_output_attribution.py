from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

METHODS = ("responses", "chat_completions", "anthropic_messages", "ollama_chat")
SENTINEL = "PRIVATE-UPSTREAM-SENTINEL"


def _failure_payload(method: str, kind: str) -> Any:
    if kind == "malformed_json":
        return SENTINEL.encode()
    if method == "responses":
        if kind == "encrypted_reasoning_only":
            return {"status": "completed", "output": [{"type": "reasoning", "encrypted_content": SENTINEL}]}
        if kind == "reasoning_only":
            return {
                "status": "completed",
                "output": [{"type": "reasoning", "content": [{"type": "reasoning_text", "text": SENTINEL}]}],
            }
        if kind == "refusal":
            return {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "refusal", "refusal": SENTINEL}]}],
            }
        if kind == "incomplete_token_limit":
            return {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}
        if kind == "provider_failed":
            return {"status": "failed", "error": {"message": SENTINEL}, "output": []}
        if kind == "unknown":
            return {"status": SENTINEL, "output": []}
        if kind == "malformed":
            return [SENTINEL]
        return {"status": "completed", "output": []}

    if method == "chat_completions":
        finish_reason = {
            "incomplete_token_limit": "length",
            "unknown": SENTINEL,
        }.get(kind)
        message: dict[str, Any] = {"role": "assistant", "content": ""}
        if kind == "reasoning_only":
            message["reasoning_content"] = SENTINEL
        elif kind == "refusal":
            message.update(content=SENTINEL, refusal=SENTINEL)
        if kind == "malformed":
            return [SENTINEL]
        return {"choices": [{"message": message, "finish_reason": finish_reason}]}

    if method == "anthropic_messages":
        stop_reason = {
            "refusal": "refusal",
            "incomplete_token_limit": "max_tokens",
            "unknown": SENTINEL,
        }.get(kind)
        content: list[dict[str, Any]] = []
        if kind == "reasoning_only":
            content = [{"type": "thinking", "thinking": SENTINEL}]
        elif kind == "refusal":
            content = [{"type": "text", "text": SENTINEL}]
        if kind == "malformed":
            return [SENTINEL]
        return {"content": content, "stop_reason": stop_reason}

    if method == "ollama_chat":
        done_reason = {
            "incomplete_token_limit": "length",
            "unknown": SENTINEL,
        }.get(kind)
        message = {"role": "assistant", "content": ""}
        if kind == "reasoning_only":
            message["thinking"] = SENTINEL
        elif kind == "refusal":
            message.update(content=SENTINEL, refusal=SENTINEL)
        if kind == "malformed":
            return [SENTINEL]
        return {"message": message, "done_reason": done_reason}

    raise AssertionError(method)


def _success_payload(method: str, kind: str) -> dict[str, Any]:
    if method == "responses":
        output = (
            [{"type": "message", "content": [{"type": "output_text", "text": "answer"}]}]
            if kind == "text"
            else [{"type": "function_call", "call_id": "call-1", "name": "lookup", "arguments": "{}"}]
        )
        return {"status": "completed", "output": output}
    if method == "chat_completions":
        message = (
            {"role": "assistant", "content": "answer"}
            if kind == "text"
            else {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
            }
        )
        return {"choices": [{"message": message}]}
    if method == "anthropic_messages":
        content = (
            [{"type": "text", "text": "answer"}]
            if kind == "text"
            else [{"type": "tool_use", "id": "call-1", "name": "lookup", "input": {}}]
        )
        return {"content": content}
    message = (
        {"role": "assistant", "content": "answer"}
        if kind == "text"
        else {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "lookup", "arguments": {}}}],
        }
    )
    return {"message": message}


async def _call_provider(monkeypatch: pytest.MonkeyPatch, method: str, payload: Any, events: list[dict[str, Any]]):
    from pallas.product.llm import provider_client as mod
    from pallas.product.llm.turn_telemetry import build_turn_event

    class FakeClient:
        async def post(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
            if isinstance(payload, bytes):
                return httpx.Response(200, content=payload)
            return httpx.Response(200, json=payload)

    async def get_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(mod, "get_llm_shared_httpx_client", get_client)
    monkeypatch.setattr(mod, "_record_usage_from_payload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mod,
        "record_turn_event",
        lambda **fields: events.append(build_turn_event(hash_key=b"provider-test-key", **fields)),
    )
    monkeypatch.setattr(
        "pallas.product.llm.provider_request_metrics.record_provider_request",
        lambda **_kwargs: None,
    )
    return await mod._post_provider_chat(
        [{"role": "user", "content": "private prompt"}],
        base_url="https://provider.example/v1",
        api_key="test-key",
        model="test-model",
        options={"model_effort": "disable"},
        tools=None,
        timeout_sec=1.0,
        request_method=method,
        telemetry_context={"turn_id": "turn-provider", "request_id": "request-provider"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("kind", ["text", "tool"])
async def test_provider_http_parsers_keep_valid_text_and_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    kind: str,
) -> None:
    events: list[dict[str, Any]] = []
    result = await _call_provider(monkeypatch, method, _success_payload(method, kind), events)

    if kind == "text":
        assert result["content"] == "answer"
        assert result.get("tool_calls") is None
    else:
        assert result["content"] == ""
        assert result["tool_calls"]
    assert events[0]["decision"] == "success"


FAILURE_CASES = [
    (method, kind, expected)
    for method in METHODS
    for kind, expected in (
        ("reasoning_only", "reasoning_only"),
        ("refusal", "refusal"),
        ("incomplete_token_limit", "incomplete_token_limit"),
        ("empty", "no_output"),
        ("unknown", "unknown"),
        ("malformed", "invalid_payload"),
        ("malformed_json", "invalid_payload"),
    )
] + [
    ("responses", "provider_failed", "provider_failed"),
    ("responses", "encrypted_reasoning_only", "reasoning_only"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "kind", "failure_class"), FAILURE_CASES)
async def test_provider_http_empty_and_rejected_outputs_have_fixed_private_attribution(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    kind: str,
    failure_class: str,
) -> None:
    from pallas.product.llm import provider_client as mod

    events: list[dict[str, Any]] = []
    with pytest.raises(mod.LlmProviderError) as caught:
        await _call_provider(monkeypatch, method, _failure_payload(method, kind), events)

    error = caught.value
    assert mod._provider_failure_class(error) == failure_class
    assert SENTINEL not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    if kind == "malformed_json":
        assert str(error) == "invalid provider payload"
        assert error.__suppress_context__ is True
    event = events[0]
    assert event["decision"] == "failed"
    assert event["failure_class"] == failure_class
    assert event["reason"] == "provider_request"
    assert SENTINEL not in json.dumps(event)


def test_provider_failure_class_rejects_unrecognized_values() -> None:
    from pallas.product.llm import provider_client as mod

    error = mod.LlmProviderError("private error", failure_class=SENTINEL)

    assert mod._provider_failure_class(error) == "unknown"
