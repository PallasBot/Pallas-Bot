"""LLM 提交前健康/熔断门禁（Bot 内核：校验 Provider，不依赖 AI Runtime）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LlmSubmitRejectReason = Literal["provider_not_configured", "daily_budget_exhausted"]

LLM_SUBMIT_USER_MESSAGE_BY_STATUS: dict[str, str] = {
    "ai_unreachable": "这会儿连不上推理服务，稍后再戳戳我吧。",
    "ai_circuit_open": "推理服务刚连续出错，我先缓一缓，过几分钟再试试。",
    "ai_unhealthy": "推理服务状态不佳，我先不接新对话了，稍后再来。",
    "provider_not_configured": "还没配好对话模型，先让维护者填好 Provider 再聊吧。",
    "daily_budget_exhausted": "今天的对话额度用完了，明天再来找我聊吧。",
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
    """兼容旧测试；内核路径不再依赖 AI health body。"""
    _ = body
    return assess_llm_kernel_submit_gate()


def assess_llm_kernel_submit_gate(cfg=None) -> LlmSubmitGateResult:
    from pallas.product.llm.config import get_llm_config, llm_provider_configured

    c = cfg or get_llm_config()
    if not llm_provider_configured(c):
        return LlmSubmitGateResult(allowed=False, status="provider_not_configured")
    if not llm_chat_daily_budget_ok(c):
        return LlmSubmitGateResult(allowed=False, status="daily_budget_exhausted")
    return LlmSubmitGateResult(allowed=True)


def llm_chat_daily_budget_ok(cfg=None) -> bool:
    """llm_chat 每日调用/输入 token 预算闸（软上限，0=不限制）。

    调用数或输入 token 任一达到上限即拒绝新对话，次日按天重置。
    """
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.daily_budget import used_today

    c = cfg or get_llm_config()
    calls_limit = int(getattr(c, "llm_chat_daily_calls_limit", 0) or 0)
    tokens_limit = int(getattr(c, "llm_chat_daily_tokens_limit", 0) or 0)
    if calls_limit <= 0 and tokens_limit <= 0:
        return True
    used = used_today("llm_chat", key="llm_chat")
    if calls_limit > 0 and used["calls"] >= calls_limit:
        return False
    if tokens_limit > 0 and used["tokens"] >= tokens_limit:
        return False
    return True


async def assess_llm_submit_gate() -> LlmSubmitGateResult:
    return assess_llm_kernel_submit_gate()
