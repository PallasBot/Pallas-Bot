from __future__ import annotations

import json
from typing import Any

import pytest

from pallas.product.llm.turn_telemetry import build_turn_event


def _capture_events(events: list[dict[str, object]]):
    def capture(**fields: object) -> None:
        events.append(build_turn_event(hash_key=b"provider-test-key", **fields))

    return capture


def _provider_call_kwargs() -> dict[str, Any]:
    return {
        "base_url": "https://provider.example/v1",
        "api_key": "sk-test",
        "model": "demo-model",
        "options": {"model_effort": "disable"},
        "tools": None,
        "timeout_sec": 5.0,
        "request_method": "chat_completions",
        "task": "llm_chat",
        "provider_id": "demo-provider",
        "telemetry_context": {
            "turn_id": "turn-provider",
            "request_id": "request-provider",
            "trigger_source": "alias",
        },
    }


@pytest.mark.asyncio
async def test_provider_success_emits_privacy_safe_attempt_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import provider_client as mod

    events: list[dict[str, object]] = []
    monkeypatch.setattr(mod, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(mod, "record_provider_request", lambda **_kwargs: None, raising=False)

    async def fake_post(_messages: list[dict[str, Any]], **_kwargs: object) -> dict[str, Any]:
        return {"role": "assistant", "content": "ok"}

    monkeypatch.setattr(mod, "_post_chat_completions", fake_post)

    result = await mod._post_provider_chat(
        [{"role": "user", "content": "secret prompt"}],
        **_provider_call_kwargs(),
    )

    assert result["content"] == "ok"
    assert len(events) == 1
    event = events[0]
    assert event["stage"] == "provider"
    assert event["decision"] == "success"
    assert event["turn_id"] == "turn-provider"
    assert event["request_id_hash"]
    assert event["provider"] == "demo-provider"
    assert event["model"] == "demo-model"
    assert event["request_method"] == "chat_completions"
    assert event["attempt"] == 1
    assert event["latency_ms"] >= 0
    serialized = json.dumps(event, ensure_ascii=False)
    assert "secret prompt" not in serialized
    assert "messages" not in event
    assert "exception" not in event


def test_provider_usage_receives_trigger_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import provider_client as mod
    from pallas.product.llm import token_metrics

    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        token_metrics,
        "record_llm_token_usage",
        lambda **kwargs: captured.append(kwargs),
    )
    mod._record_usage_from_payload(
        {"usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        task="llm_chat",
        provider_id="demo-provider",
        model="demo-model",
        telemetry_context={"trigger_source": "alias"},
    )

    assert captured[0]["trigger_source"] == "alias"


def test_telemetry_metadata_preserves_trigger_source() -> None:
    from pallas.product.llm.turn_telemetry import telemetry_metadata

    assert telemetry_metadata({"turn_id": "turn-1", "speak_trigger": "followup"}) == {
        "turn_id": "turn-1",
        "trigger_source": "followup",
    }


@pytest.mark.asyncio
async def test_provider_tool_choice_retry_emits_failed_and_success_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import provider_client as mod

    mod.clear_tool_choice_compatibility_cache()
    events: list[dict[str, object]] = []
    monkeypatch.setattr(mod, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(mod, "record_provider_request", lambda **_kwargs: None, raising=False)
    calls = 0

    async def fake_post(_messages: list[dict[str, Any]], **kwargs: object) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert kwargs["options"]["tool_choice"] == "required"
            raise mod.LlmProviderError("tool_choice unsupported by provider", status=400)
        assert kwargs["options"]["tool_choice"] == "auto"
        return {"role": "assistant", "content": "retried"}

    monkeypatch.setattr(mod, "_post_chat_completions", fake_post)
    kwargs = _provider_call_kwargs()
    kwargs["options"] = {"model_effort": "disable", "tool_choice": "required"}
    kwargs["tools"] = [{"type": "function", "function": {"name": "lookup"}}]

    result = await mod._post_provider_chat(
        [{"role": "user", "content": "secret prompt"}],
        **kwargs,
    )

    assert result["content"] == "retried"
    assert [event["decision"] for event in events] == ["failed", "success"]
    assert [event["attempt"] for event in events] == [1, 2]
    assert all(event["turn_id"] == "turn-provider" for event in events)
    assert events[0]["failure_class"] == "http_400"
    assert events[0]["reason"] == "tool_choice_retry"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "failure_class"),
    [
        (TimeoutError("private timeout detail"), "timeout"),
        (None, "http_503"),
    ],
)
async def test_provider_failure_emits_fixed_failure_class_without_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException | None,
    failure_class: str,
) -> None:
    from pallas.product.llm import provider_client as mod

    events: list[dict[str, object]] = []
    monkeypatch.setattr(mod, "record_turn_event", _capture_events(events))
    monkeypatch.setattr(mod, "record_provider_request", lambda **_kwargs: None, raising=False)

    async def fake_post(_messages: list[dict[str, Any]], **_kwargs: object) -> dict[str, Any]:
        if error is None:
            raise mod.LlmProviderError("private upstream detail", status=503)
        raise error

    monkeypatch.setattr(mod, "_post_chat_completions", fake_post)

    with pytest.raises((TimeoutError, mod.LlmProviderError)):
        await mod._post_provider_chat(
            [{"role": "user", "content": "secret prompt"}],
            **_provider_call_kwargs(),
        )

    assert len(events) == 1
    event = events[0]
    assert event["decision"] == "failed"
    assert event["failure_class"] == failure_class
    assert "private timeout detail" not in json.dumps(event)
    assert "private upstream detail" not in json.dumps(event)
