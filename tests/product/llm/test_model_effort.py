from __future__ import annotations

from pallas.product.llm.provider_client import apply_model_effort_to_payload


def test_apply_model_effort_reasoning() -> None:
    payload: dict = {"model": "gpt-5"}
    apply_model_effort_to_payload(payload, {"model_effort": "high"}, model="gpt-5")
    assert payload["reasoning_effort"] == "high"


def test_apply_model_effort_disable_deepseek() -> None:
    payload: dict = {"model": "deepseek-v4-flash"}
    apply_model_effort_to_payload(payload, {"model_effort": "disable"}, model="deepseek-v4-flash")
    assert payload["thinking"] == {"type": "disabled"}


def test_apply_model_effort_non_deepseek_chat_disable_thinking() -> None:
    payload: dict = {"model": "qwen3.7-max"}
    apply_model_effort_to_payload(payload, {"model_effort": "disable"}, model="qwen3.7-max")
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_apply_model_effort_deepseek_default_disables_thinking() -> None:
    payload: dict = {"model": "deepseek-v4-flash"}
    apply_model_effort_to_payload(payload, {}, model="deepseek-v4-flash")
    assert payload["thinking"] == {"type": "disabled"}


def test_apply_model_effort_deepseek_tools_with_high_keeps_thinking() -> None:
    payload: dict = {
        "model": "deepseek-v4-flash",
        "tools": [{"type": "function", "function": {"name": "demo"}}],
    }
    apply_model_effort_to_payload(payload, {"model_effort": "high"}, model="deepseek-v4-flash")
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"


def test_apply_model_effort_deepseek_enable() -> None:
    payload: dict = {"model": "deepseek-v4-flash"}
    apply_model_effort_to_payload(payload, {"model_effort": "enable"}, model="deepseek-v4-flash")
    assert payload["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in payload


def test_apply_model_effort_deepseek_responses_disables_with_reasoning_none() -> None:
    payload: dict = {
        "model": "deepseek-v4-flash",
        "tools": [{"type": "function", "name": "demo"}],
    }
    apply_model_effort_to_payload(
        payload,
        {"model_effort": "disable"},
        model="deepseek-v4-flash",
        request_method="responses",
    )
    assert payload["reasoning"] == {"effort": "none"}
    assert "thinking" not in payload


def test_apply_model_effort_deepseek_responses_tools_with_high() -> None:
    payload: dict = {
        "model": "deepseek-v4-flash",
        "tools": [{"type": "function", "name": "demo"}],
    }
    apply_model_effort_to_payload(
        payload,
        {"model_effort": "high"},
        model="deepseek-v4-flash",
        request_method="responses",
    )
    assert payload["reasoning"] == {"effort": "high"}
    assert "thinking" not in payload


def test_apply_model_effort_deepseek_responses_enables_high() -> None:
    payload: dict = {"model": "deepseek-v4-flash"}
    apply_model_effort_to_payload(
        payload,
        {"model_effort": "high"},
        model="deepseek-v4-flash",
        request_method="responses",
    )
    assert payload["reasoning"] == {"effort": "high"}
    assert "thinking" not in payload


def test_apply_model_effort_responses_openai_uses_reasoning_object() -> None:
    payload: dict = {"model": "gpt-5"}
    apply_model_effort_to_payload(
        payload,
        {"model_effort": "medium"},
        model="gpt-5",
        request_method="responses",
    )
    assert payload["reasoning"] == {"effort": "medium"}
    assert "reasoning_effort" not in payload


def test_apply_model_effort_anthropic_budget() -> None:
    payload: dict = {"model": "claude-sonnet-4-5", "max_tokens": 512}
    apply_model_effort_to_payload(
        payload,
        {"model_effort": "high"},
        model="claude-sonnet-4-5",
        request_method="anthropic_messages",
    )
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 8192}
    assert payload["max_tokens"] == 8192 + 1024


def test_apply_model_effort_anthropic_default_skips() -> None:
    payload: dict = {"model": "claude-sonnet-4-5", "max_tokens": 1024}
    apply_model_effort_to_payload(
        payload,
        {},
        model="claude-sonnet-4-5",
        request_method="anthropic_messages",
    )
    assert "thinking" not in payload
