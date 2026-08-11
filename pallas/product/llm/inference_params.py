"""按账号表达气质派生温度，并按任务复杂度分配输出预算。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from pallas.product.persona.model import ResolvedPersona

_BASE_TEMPERATURE = 0.55
ChatReplyBudgetBand = Literal["casual", "serious", "tool"]
TaskBudgetKey = Literal[
    "llm_chat",
    "chat",
    "drunk",
    "affect_refine",
    "memory_extract",
    "turn_decision",
    "repeater.semantic_style",
    "sticker_vision",
    "vision_messages",
    "memory_graph_extract",
    "memory_graph_hiergraph",
    "catchphrase_extract",
    "offline_quality_eval",
]

_TASK_TOKEN_BUDGETS: dict[TaskBudgetKey, int] = {
    "llm_chat": 240,
    "chat": 240,
    "drunk": 240,
    "affect_refine": 512,
    "memory_extract": 160,
    "turn_decision": 48,
    "repeater.semantic_style": 96,
    "sticker_vision": 32,
    "vision_messages": 256,
    "memory_graph_extract": 1200,
    "memory_graph_hiergraph": 1500,
    "catchphrase_extract": 200,
    "offline_quality_eval": 96,
}
_CHAT_TOOLS_TOKEN_BUDGET = 360
_CHAT_REPLY_TOKEN_BUDGETS: dict[ChatReplyBudgetBand, int] = {
    "casual": _TASK_TOKEN_BUDGETS["llm_chat"],
    "serious": 256,
    "tool": 512,
}


def derive_llm_inference_params(
    persona: ResolvedPersona,
    *,
    mode: str = "normal",
) -> tuple[float | None, int | None]:
    """返回温度与句长上限；醉酒模式不传温度。"""
    if str(mode or "normal").strip().lower() == "drunk":
        return None, task_token_budget("chat")

    temperature = _BASE_TEMPERATURE
    temperature += float(persona.chaos_bias) * 0.25
    temperature += max(0.0, float(persona.warmth)) * 0.08
    temperature += max(0.0, float(persona.assertiveness)) * 0.06
    temperature += max(0.0, float(persona.bluntness)) * 0.05
    temperature -= max(0.0, -float(persona.warmth)) * 0.05
    temperature -= max(0.0, -float(persona.bluntness)) * 0.03
    temperature = max(0.2, min(1.1, temperature))
    return temperature, task_token_budget("llm_chat")


def task_token_budget(
    task: TaskBudgetKey,
    *,
    tools_enabled: bool = False,
    operation: Literal["", "vision"] = "",
) -> int:
    normalized = str(task).strip().lower()
    if normalized not in _TASK_TOKEN_BUDGETS:
        raise ValueError(f"unknown LLM task budget key: {normalized or '<empty>'}")
    key = cast("TaskBudgetKey", normalized)
    base = _TASK_TOKEN_BUDGETS[key]
    if tools_enabled and normalized in {"llm_chat", "chat"}:
        return _CHAT_TOOLS_TOKEN_BUDGET
    if normalized == "repeater.semantic_style" and str(operation).strip().lower() == "vision":
        return 100
    return base


def chat_reply_token_budget(band: ChatReplyBudgetBand) -> int:
    normalized = str(band or "").strip().lower()
    if normalized not in _CHAT_REPLY_TOKEN_BUDGETS:
        raise ValueError(f"unknown chat reply budget band: {normalized or '<empty>'}")
    return _CHAT_REPLY_TOKEN_BUDGETS[cast("ChatReplyBudgetBand", normalized)]


def resolve_task_token_budget(
    task: str,
    *,
    tools_enabled: bool,
    requested: int | None,
) -> int:
    normalized = str(task or "").strip().lower()
    if normalized not in _TASK_TOKEN_BUDGETS:
        raise ValueError(f"unknown LLM task budget key: {normalized or '<empty>'}")
    key = cast("TaskBudgetKey", normalized)
    budget = task_token_budget(key, tools_enabled=tools_enabled)
    if normalized in {"llm_chat", "chat", "drunk"}:
        if requested is None:
            return budget
        max_band: ChatReplyBudgetBand = "tool" if tools_enabled else "serious"
        requested_budget = min(chat_reply_token_budget(max_band), max(1, int(requested)))
        return max(budget, requested_budget)
    if requested is not None:
        return max(1, int(requested))
    return budget
