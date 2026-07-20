"""Bot 内核闲聊：进程内补全并投递结果。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from nonebot import logger

from pallas.product.llm.governance import LlmChatGovernance
from pallas.product.llm.models import ChatSubmitRequest, ChatSubmitResult
from pallas.product.llm.repeater_limit import (
    check_repeater_llm_allowed,
    refresh_repeater_group_cooldown,
    release_repeater_llm_slot,
    try_acquire_repeater_llm_slot,
)
from pallas.product.llm.tool_loop import complete_with_tool_loop

if TYPE_CHECKING:
    from pallas.core.platform.observability import SlowPathTimer
    from pallas.product.llm.config import LlmConfig


async def deliver_llm_chat_result(
    task_id: str,
    *,
    status: str,
    text: str | None = None,
    agent_trace: str | None = None,
    history_summary: str | None = None,
    history_keep_messages: int | None = None,
) -> dict[str, str]:
    """内核与 AI 回调共用的投递入口（不经 HTTP）。"""
    from pallas.core.platform.ai_callback.runner import deliver_llm_chat_result as _deliver

    return await _deliver(
        task_id,
        status=status,
        text=text,
        agent_trace=agent_trace,
        history_summary=history_summary,
        history_keep_messages=history_keep_messages,
    )


async def run_kernel_chat_job(
    request_id: str,
    *,
    system_prompt: str | None,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
    cfg: LlmConfig,
) -> None:
    try:
        content, assistant_message = await complete_with_tool_loop(
            system_prompt=system_prompt,
            messages=messages,
            metadata=metadata,
            cfg=cfg,
        )
        agent_trace_raw = assistant_message.get("_agent_trace")
        agent_trace = None
        if isinstance(agent_trace_raw, dict):
            agent_trace = json.dumps(agent_trace_raw, ensure_ascii=False)
        await deliver_llm_chat_result(
            request_id,
            status="success",
            text=content,
            agent_trace=agent_trace,
        )
    except Exception:
        logger.exception("llm kernel chat failed: request_id={}", request_id)
        try:
            await deliver_llm_chat_result(request_id, status="failed")
        except Exception:
            logger.exception("llm kernel deliver failure failed: request_id={}", request_id)


def schedule_kernel_chat_job(
    request_id: str,
    *,
    system_prompt: str | None,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
    cfg: LlmConfig,
) -> None:
    asyncio.create_task(
        run_kernel_chat_job(
            request_id,
            system_prompt=system_prompt,
            messages=messages,
            metadata=metadata,
            cfg=cfg,
        )
    )


async def submit_kernel_repeater_chat_task(
    request: ChatSubmitRequest,
    *,
    system_prompt: str | None,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
    timer: SlowPathTimer,
    message_count: int,
    cfg: LlmConfig,
) -> ChatSubmitResult:
    if request.bot_id is None or request.group_id is None:
        timer.finish(status="missing_group", request_id=request.request_id)
        return ChatSubmitResult(status="missing_group", ok=False)

    skip_reason = await check_repeater_llm_allowed(int(request.bot_id), int(request.group_id), cfg=cfg)
    if skip_reason:
        timer.finish(status=skip_reason, request_id=request.request_id)
        return ChatSubmitResult(status=skip_reason, ok=False)

    slot = await try_acquire_repeater_llm_slot(cfg=cfg)
    if slot is None:
        timer.finish(status="repeater_busy", request_id=request.request_id)
        return ChatSubmitResult(status="repeater_busy", ok=False)
    try:
        schedule_kernel_chat_job(
            request.request_id,
            system_prompt=system_prompt,
            messages=messages,
            metadata=metadata,
            cfg=cfg,
        )
        await refresh_repeater_group_cooldown(int(request.bot_id), int(request.group_id))
    finally:
        release_repeater_llm_slot(slot)
    timer.mark("kernel_schedule")
    timer.finish(status="processing", request_id=request.request_id, message_count=message_count)
    return ChatSubmitResult(task_id=request.request_id, status="processing", ok=True)


async def submit_kernel_llm_chat_task(
    request: ChatSubmitRequest,
    *,
    system_prompt: str | None,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
    timer: SlowPathTimer,
    message_count: int,
    cfg: LlmConfig,
) -> ChatSubmitResult:
    async with LlmChatGovernance(wait=False, cfg=cfg) as gov:
        if gov.skipped:
            timer.finish(status="skipped_busy", request_id=request.request_id)
            return ChatSubmitResult(status="busy", ok=False)
        schedule_kernel_chat_job(
            request.request_id,
            system_prompt=system_prompt,
            messages=messages,
            metadata=metadata,
            cfg=cfg,
        )
    timer.mark("kernel_schedule")
    timer.finish(status="processing", request_id=request.request_id, message_count=message_count)
    return ChatSubmitResult(task_id=request.request_id, status="processing", ok=True)
