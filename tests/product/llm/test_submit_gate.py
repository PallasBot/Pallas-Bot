from __future__ import annotations

import pytest

from pallas.product.llm.submit_gate import (
    assess_llm_kernel_submit_gate,
    assess_llm_submit_gate_from_body,
    user_message_for_submit_status,
)


def test_user_message_for_submit_status_circuit_open() -> None:
    text = user_message_for_submit_status("ai_circuit_open")
    assert text
    assert "连续出错" in text


def test_assess_submit_gate_from_body_always_uses_kernel() -> None:
    result = assess_llm_submit_gate_from_body({"llm": {"circuit_state": "open"}})
    assert result.allowed is False or result.allowed is True
    # body 已忽略；结果等于内核门禁
    assert result == assess_llm_kernel_submit_gate()


@pytest.mark.asyncio
async def test_submit_chat_task_rejects_when_provider_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.client import submit_chat_task
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.models import ChatSubmitRequest
    from pallas.product.llm.submit_gate import LlmSubmitGateResult

    async def reject_gate() -> LlmSubmitGateResult:
        return LlmSubmitGateResult(allowed=False, status="provider_not_configured")

    monkeypatch.setattr("pallas.product.llm.client.assess_llm_submit_gate", reject_gate)

    cfg = LlmConfig(
        llm_chat_enabled=True,
        use_unified_chat_api=True,
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-provider",
            session_id="sess",
            user_text="hello",
            system_prompt="sys",
            task="llm_chat",
        ),
        cfg=cfg,
    )
    assert result.ok is False
    assert result.status == "provider_not_configured"


def test_llm_chat_daily_budget_ok_when_unlimited(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.submit_gate import llm_chat_daily_budget_ok

    cfg = LlmConfig(llm_chat_daily_calls_limit=0, llm_chat_daily_tokens_limit=0)
    assert llm_chat_daily_budget_ok(cfg) is True


def test_llm_chat_daily_budget_ok_respects_calls_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.submit_gate import llm_chat_daily_budget_ok

    monkeypatch.setattr(
        "pallas.product.llm.daily_budget.used_today",
        lambda *a, **k: {"calls": 5.0, "tokens": 100.0, "cost": 0.0},
    )
    cfg = LlmConfig(llm_chat_daily_calls_limit=5, llm_chat_daily_tokens_limit=0)
    assert llm_chat_daily_budget_ok(cfg) is False
    cfg2 = LlmConfig(llm_chat_daily_calls_limit=6, llm_chat_daily_tokens_limit=0)
    assert llm_chat_daily_budget_ok(cfg2) is True


def test_llm_chat_daily_budget_ok_respects_tokens_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.submit_gate import llm_chat_daily_budget_ok

    monkeypatch.setattr(
        "pallas.product.llm.daily_budget.used_today",
        lambda *a, **k: {"calls": 1.0, "tokens": 2000.0, "cost": 0.0},
    )
    cfg = LlmConfig(llm_chat_daily_calls_limit=0, llm_chat_daily_tokens_limit=2000)
    assert llm_chat_daily_budget_ok(cfg) is False
    cfg2 = LlmConfig(llm_chat_daily_calls_limit=0, llm_chat_daily_tokens_limit=2001)
    assert llm_chat_daily_budget_ok(cfg2) is True


def test_assess_kernel_gate_rejects_when_daily_budget_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.submit_gate import assess_llm_kernel_submit_gate

    monkeypatch.setattr(
        "pallas.product.llm.submit_gate.llm_chat_daily_budget_ok",
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        "pallas.product.llm.config.llm_provider_configured",
        lambda *a, **k: True,
    )
    cfg = LlmConfig(llm_chat_daily_calls_limit=1)
    result = assess_llm_kernel_submit_gate(cfg)
    assert result.allowed is False
    assert result.status == "daily_budget_exhausted"
