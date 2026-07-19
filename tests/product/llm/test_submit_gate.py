from __future__ import annotations

import pytest

from pallas.product.llm.submit_gate import (
    LLM_SUBMIT_REJECT_FAILURE_THRESHOLD,
    assess_llm_submit_gate_from_body,
    user_message_for_submit_status,
)


def test_user_message_for_submit_status_circuit_open() -> None:
    text = user_message_for_submit_status("ai_circuit_open")
    assert text
    assert "连续出错" in text


def test_assess_submit_gate_rejects_open_circuit() -> None:
    body = {"llm": {"circuit_state": "open", "consecutive_failures": 2}}
    result = assess_llm_submit_gate_from_body(body)
    assert result.allowed is False
    assert result.status == "ai_circuit_open"


def test_assess_submit_gate_rejects_unhealthy_after_failures() -> None:
    body = {
        "llm": {
            "health_state": "unhealthy",
            "consecutive_failures": LLM_SUBMIT_REJECT_FAILURE_THRESHOLD,
            "circuit_state": "closed",
        }
    }
    result = assess_llm_submit_gate_from_body(body)
    assert result.allowed is False
    assert result.status == "ai_unhealthy"


def test_assess_submit_gate_rejects_all_providers_unreachable() -> None:
    body = {
        "llm": {
            "health_state": "degraded",
            "provider_status": [
                {"id": "local", "enabled": True, "reachable": False},
                {"id": "remote", "enabled": True, "reachable": False},
            ],
        }
    }
    result = assess_llm_submit_gate_from_body(body)
    assert result.allowed is False
    assert result.status == "ai_unreachable"


def test_assess_submit_gate_allows_healthy() -> None:
    body = {
        "llm": {
            "health_state": "healthy",
            "circuit_state": "closed",
            "provider_status": [{"id": "local", "enabled": True, "reachable": True}],
        }
    }
    result = assess_llm_submit_gate_from_body(body)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_submit_chat_task_rejects_when_circuit_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.client import submit_chat_task
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.models import ChatSubmitRequest
    from pallas.product.llm.submit_gate import LlmSubmitGateResult

    async def reject_gate() -> LlmSubmitGateResult:
        return LlmSubmitGateResult(allowed=False, status="ai_circuit_open")

    monkeypatch.setattr("pallas.product.llm.client.assess_llm_submit_gate", reject_gate)

    cfg = LlmConfig(
        ai_server_host="127.0.0.1",
        ai_server_port=9099,
        llm_chat_enabled=True,
        use_unified_chat_api=True,
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-circuit",
            session_id="sess",
            user_text="hello",
            system_prompt="sys",
            task="llm_chat",
        ),
        cfg=cfg,
    )
    assert result.ok is False
    assert result.status == "ai_circuit_open"
