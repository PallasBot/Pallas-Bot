"""LLM 提交前健康/熔断门禁（事实源 = AI /health 缓存）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pallas.core.shared.ai_health_cache import cached_ai_health_body
from pallas.core.shared.ai_runtime_failure import CIRCUIT_OPEN
from pallas.product.llm.ai_health_parse import llm_health_circuit, llm_health_summary
from pallas.product.llm.startup_probe import probe_ai_service_health

LLM_SUBMIT_REJECT_FAILURE_THRESHOLD = 3

LlmSubmitRejectReason = Literal["ai_unreachable", "ai_circuit_open", "ai_unhealthy"]

LLM_SUBMIT_USER_MESSAGE_BY_STATUS: dict[str, str] = {
    "ai_unreachable": "这会儿连不上推理服务，稍后再戳戳我吧。",
    "ai_circuit_open": "推理服务刚连续出错，我先缓一缓，过几分钟再试试。",
    "ai_unhealthy": "推理服务状态不佳，我先不接新对话了，稍后再来。",
    "busy": "此刻思绪有些拥挤，稍后再戳戳我吧。",
    "request_failed": "我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。",
    "empty_response": "我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。",
    "invalid_response": "我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。",
}


@dataclass(frozen=True, slots=True)
class LlmSubmitGateResult:
    allowed: bool
    status: str = ""


def user_message_for_submit_status(status: str) -> str | None:
    text = LLM_SUBMIT_USER_MESSAGE_BY_STATUS.get(str(status or "").strip())
    return text or None


def assess_llm_submit_gate_from_body(body: object | None) -> LlmSubmitGateResult:
    if not isinstance(body, dict):
        return LlmSubmitGateResult(allowed=False, status="ai_unreachable")

    circuit = llm_health_circuit(body)
    if circuit and str(circuit.get("circuit_state") or "").strip().lower() == CIRCUIT_OPEN:
        return LlmSubmitGateResult(allowed=False, status="ai_circuit_open")

    summary = llm_health_summary(body)
    consecutive = int(circuit.get("consecutive_failures") or 0) if circuit else 0
    if summary:
        health_state = str(summary.get("health_state") or "").strip().lower()
        if health_state == "unhealthy" and consecutive >= LLM_SUBMIT_REJECT_FAILURE_THRESHOLD:
            return LlmSubmitGateResult(allowed=False, status="ai_unhealthy")

        providers = summary.get("provider_status")
        if isinstance(providers, list):
            enabled = [row for row in providers if isinstance(row, dict) and row.get("enabled")]
            if enabled and all(row.get("reachable") is False for row in enabled):
                return LlmSubmitGateResult(allowed=False, status="ai_unreachable")

    return LlmSubmitGateResult(allowed=True)


async def assess_llm_submit_gate() -> LlmSubmitGateResult:
    from pallas.product.llm.config import get_llm_config

    cfg = get_llm_config()
    if not cfg.use_unified_chat_api:
        return LlmSubmitGateResult(allowed=True)

    body = cached_ai_health_body()
    if body is None:
        result = await probe_ai_service_health(timeout_sec=2.0)
        if not result.get("ok"):
            return LlmSubmitGateResult(allowed=False, status="ai_unreachable")
        body = result.get("body")
    return assess_llm_submit_gate_from_body(body)
