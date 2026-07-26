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


def test_apply_model_effort_deepseek_default_disables_thinking() -> None:
    payload: dict = {"model": "deepseek-v4-flash"}
    apply_model_effort_to_payload(payload, {}, model="deepseek-v4-flash")
    assert payload["thinking"] == {"type": "disabled"}


def test_apply_model_effort_deepseek_tools_disables_thinking() -> None:
    payload: dict = {
        "model": "deepseek-v4-flash",
        "tools": [{"type": "function", "function": {"name": "demo"}}],
    }
    apply_model_effort_to_payload(payload, {"model_effort": "high"}, model="deepseek-v4-flash")
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload
