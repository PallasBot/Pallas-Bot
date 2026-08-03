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


from pallas.product.llm.delivery import deliver_llm_chat_result


def system_prompt_with_reply_target(system_prompt: str | None, metadata: dict[str, Any]) -> str | None:
    from pallas.product.llm.current_turn_decision import build_reply_target_instruction

    instruction = build_reply_target_instruction(metadata.get("reply_target"))
    if not instruction:
        return system_prompt
    return f"{str(system_prompt or '').strip()}\n\n【本轮回复目标】\n{instruction}".strip()


async def run_kernel_chat_job(
    request_id: str,
    *,
    system_prompt: str | None,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
    cfg: LlmConfig,
) -> None:
    try:
        generation_system_prompt = system_prompt_with_reply_target(system_prompt, metadata)
        content, assistant_message = await complete_with_tool_loop(
            system_prompt=generation_system_prompt,
            messages=messages,
            metadata=metadata,
            cfg=cfg,
        )
        from pallas.product.llm.persona_output_firewall import (
            persona_output_firewall_policy_from_data,
            persona_output_retry_instruction,
            redact_agent_trace_for_firewall,
            resolve_persona_output,
        )

        policy = persona_output_firewall_policy_from_data(cfg.llm_persona_output_firewall)
        self_aliases = [str(item) for item in metadata.get("self_aliases", []) if str(item).strip()]
        fallback_text = str(metadata.get("conversation_fallback_text") or "").strip()
        current_user_text = next(
            (
                str(item.get("content") or "")
                for item in reversed(messages)
                if str(item.get("role") or "").strip().lower() == "user"
            ),
            "",
        )
        raw_social_action = metadata.get("social_action")
        social_action = str(getattr(raw_social_action, "value", raw_social_action) or "").strip().upper()
        reply_target = str(metadata.get("reply_target") or "").strip().lower()
        decision = resolve_persona_output(
            content,
            policy=policy,
            self_aliases=self_aliases,
            fallback_text=fallback_text,
            current_user_text=current_user_text,
            social_action=social_action,
            reply_target=reply_target,
        )
        initial_quality = decision.trace.get("chat_quality")
        initial_agent_trace = assistant_message.get("_agent_trace")
        tool_loop_ran = (
            isinstance(initial_agent_trace, dict) and int(initial_agent_trace.get("tool_call_count") or 0) > 0
        )
        if decision.action == "retry" and tool_loop_ran:
            decision = resolve_persona_output(
                content,
                policy=policy,
                self_aliases=self_aliases,
                fallback_text=fallback_text,
                retry_count=policy.max_retries,
                current_user_text=current_user_text,
                social_action=social_action,
                reply_target=reply_target,
            )
        elif decision.action == "retry":
            retry_instruction = persona_output_retry_instruction(list((initial_quality or {}).get("rule_ids") or []))
            retry_messages = [
                *messages,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": retry_instruction,
                },
            ]
            content, assistant_message = await complete_with_tool_loop(
                system_prompt=generation_system_prompt,
                messages=retry_messages,
                metadata={**metadata, "persona_output_retry": 1},
                cfg=cfg,
            )
            decision = resolve_persona_output(
                content,
                policy=policy,
                self_aliases=self_aliases,
                fallback_text=fallback_text,
                retry_count=1,
                current_user_text=current_user_text,
                social_action=social_action,
                reply_target=reply_target,
            )
        content = decision.text
        agent_trace_raw = assistant_message.get("_agent_trace")
        if int(decision.trace.get("rule_count") or 0) > 0:
            agent_trace_raw = redact_agent_trace_for_firewall(agent_trace_raw)
        agent_trace = None
        trace = {
            "status": "success",
            "agent_trace": agent_trace_raw if isinstance(agent_trace_raw, dict) else None,
            "persona_output_firewall": decision.trace,
            "chat_reply_quality": {
                "initial": initial_quality,
                "final": decision.trace.get("chat_quality"),
            },
        }
        if isinstance(agent_trace_raw, dict):
            agent_trace = json.dumps(agent_trace_raw, ensure_ascii=False)
            trace.update(agent_trace_raw)
        trace["retrieval_mode"] = metadata.get("retrieval_mode")
        trace["reply_target"] = metadata.get("reply_target")
        from pallas.product.llm.runtime_debug import append_runtime_trace

        append_runtime_trace(request_id=request_id, trace=trace)
        delivery_kwargs = {"status": "success", "text": content, "agent_trace": agent_trace}
        if decision.action == "silent":
            delivery_kwargs["suppress_empty_fallback"] = True
        await deliver_llm_chat_result(request_id, **delivery_kwargs)
    except Exception as exc:
        logger.exception("llm kernel chat failed: request_id={}", request_id)
        try:
            from pallas.product.llm.runtime_debug import append_runtime_trace

            append_runtime_trace(
                request_id=request_id,
                trace={"status": "failed", "error": str(exc)[:240], "agent_trace": None},
            )
        except Exception:
            logger.exception("llm kernel runtime trace failure: request_id={}", request_id)
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

    tier = str(request.scene_tier or "weak").strip().lower() or "weak"
    skip_reason = await check_repeater_llm_allowed(
        int(request.bot_id),
        int(request.group_id),
        cfg=cfg,
        scene_tier=tier,
    )
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
        await refresh_repeater_group_cooldown(int(request.bot_id), int(request.group_id), scene_tier=tier)
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
