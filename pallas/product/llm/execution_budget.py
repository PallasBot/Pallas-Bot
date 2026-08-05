"""共享 LLM 执行预算：高压下按交互优先级静默拒绝低优先级任务。"""

from __future__ import annotations

import asyncio
from typing import Literal

from .config import LlmConfig, get_llm_config

LlmExecutionPriority = Literal["explicit", "ambient", "repeater_strong", "repeater_weak", "proactive"]
_PRIORITY_ORDER: tuple[LlmExecutionPriority, ...] = (
    "explicit",
    "ambient",
    "repeater_strong",
    "repeater_weak",
    "proactive",
)

_budget_sem: asyncio.BoundedSemaphore | None = None
_budget_limit: int | None = None
_skipped_by_priority: dict[str, int] = dict.fromkeys(_PRIORITY_ORDER, 0)


def clear_llm_execution_budget_state() -> None:
    global _budget_sem, _budget_limit
    _budget_sem = None
    _budget_limit = None
    for priority in _PRIORITY_ORDER:
        _skipped_by_priority[priority] = 0


def normalize_llm_execution_priority(value: str | None) -> LlmExecutionPriority:
    normalized = str(value or "").strip().lower()
    if normalized in _PRIORITY_ORDER:
        return normalized  # type: ignore[return-value]
    return "repeater_weak"


def llm_execution_concurrency_limit(cfg: LlmConfig | None = None) -> int:
    c = cfg or get_llm_config()
    return max(1, int(c.llm_shared_max_concurrency))


def _priority_capacity(priority: LlmExecutionPriority, *, cfg: LlmConfig) -> int:
    limit = llm_execution_concurrency_limit(cfg)
    index = _PRIORITY_ORDER.index(priority)
    return max(1, limit - index)


def _budget_sem_for(cfg: LlmConfig) -> asyncio.BoundedSemaphore:
    global _budget_sem, _budget_limit
    limit = llm_execution_concurrency_limit(cfg)
    if _budget_sem is None or _budget_limit != limit:
        _budget_sem = asyncio.BoundedSemaphore(limit)
        _budget_limit = limit
    return _budget_sem


class LlmExecutionSlot:
    __slots__ = ("acquired",)

    def __init__(self) -> None:
        self.acquired = False


async def try_acquire_llm_execution_slot(
    priority: str | None,
    *,
    cfg: LlmConfig | None = None,
) -> LlmExecutionSlot | None:
    c = cfg or get_llm_config()
    if not c.llm_governance_enabled:
        slot = LlmExecutionSlot()
        slot.acquired = True
        return slot
    resolved = normalize_llm_execution_priority(priority)
    sem = _budget_sem_for(c)
    # 不等待、不排队：给更高优先级保留尾部容量。
    if sem.locked() or sem._value < llm_execution_concurrency_limit(c) - _priority_capacity(resolved, cfg=c) + 1:
        _skipped_by_priority[resolved] += 1
        return None
    await sem.acquire()
    slot = LlmExecutionSlot()
    slot.acquired = True
    return slot


def release_llm_execution_slot(slot: LlmExecutionSlot | None, *, cfg: LlmConfig | None = None) -> None:
    if slot is None or not slot.acquired:
        return
    c = cfg or get_llm_config()
    if c.llm_governance_enabled:
        _budget_sem_for(c).release()
    slot.acquired = False


def llm_execution_budget_snapshot() -> dict[str, int]:
    return {f"llm_budget_skipped_{priority}": count for priority, count in _skipped_by_priority.items()}
