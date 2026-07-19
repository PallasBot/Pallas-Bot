from __future__ import annotations

from nonebot import logger

from pallas.core.platform.observability import SlowPathTimer, slow_path_threshold_ms
from pallas.core.shared.ai_capability_request import build_llm_chat_capability_body
from pallas.core.shared.utils import HTTPXClient

from .budget import trim_messages_to_char_budget
from .config import LlmConfig, get_llm_config, llm_server_base_url
from .governance import LlmChatGovernance
from .kernel.memory_governance import can_write_runtime_state_summary, runtime_state_summary_metadata
from .legacy_guard import assess_legacy_chat_submit
from .message_guard import format_user_turn
from .models import ChatCompletionMessage, ChatSubmitRequest, ChatSubmitResult
from .repeater_limit import (
    check_repeater_llm_allowed,
    is_repeater_llm_task,
    refresh_repeater_group_cooldown,
    release_repeater_llm_slot,
    try_acquire_repeater_llm_slot,
)
from .session_store import build_llm_chat_messages, format_legacy_transcript, is_llm_session_store_available
from .submit_gate import assess_llm_submit_gate
from .task_routing import resolve_submit_task_name, resolve_task_route_chain, serialize_task_route


def chat_endpoint_path(cfg: LlmConfig | None = None) -> str:
    c = cfg or get_llm_config()
    if c.use_unified_chat_api:
        return c.unified_chat_endpoint
    return c.legacy_chat_endpoint


async def resolve_chat_messages(
    request: ChatSubmitRequest,
    *,
    cfg: LlmConfig | None = None,
) -> list[ChatCompletionMessage]:
    c = cfg or get_llm_config()
    task = str(request.task or "").strip().lower()
    if is_repeater_llm_task(task):
        return build_chat_messages(request.user_text, max_len=c.user_message_max_len)
    if is_llm_session_store_available() and request.bot_id is not None and request.user_id is not None:
        return await build_llm_chat_messages(
            int(request.bot_id),
            request.group_id,
            int(request.user_id),
            request.user_text,
            cfg=c,
        )
    user_turn = format_user_turn(request.user_text, max_len=c.user_message_max_len)
    if not user_turn:
        return []
    return [ChatCompletionMessage(role="user", content=user_turn)]


async def submit_chat_task(request: ChatSubmitRequest, *, cfg: LlmConfig | None = None) -> ChatSubmitResult:
    c = cfg or get_llm_config()
    if not c.llm_chat_enabled:
        return ChatSubmitResult(status="llm_chat_disabled", ok=False)
    timer = SlowPathTimer(
        "llm.submit_chat_task",
        threshold_ms=slow_path_threshold_ms("LLM_CHAT_SLOW_PATH_MS", 500.0),
    )
    messages = await resolve_chat_messages(request, cfg=c)
    timer.mark("resolve_messages")
    if not messages:
        return ChatSubmitResult(status="empty_user_message", ok=False)

    if c.llm_chat_char_budget > 0:
        messages = trim_messages_to_char_budget(
            messages,
            system_prompt=request.system_prompt,
            budget_chars=c.llm_chat_char_budget,
        )
        timer.mark("trim_budget")

    use_pg_session = is_llm_session_store_available() and request.bot_id is not None and request.user_id is not None
    task_name = resolve_submit_task_name(request.task, request.mode)

    base = llm_server_base_url(c)
    endpoint = chat_endpoint_path(c)
    url = f"{base}{endpoint}/{request.request_id}"

    legacy_reject = assess_legacy_chat_submit(c)
    if legacy_reject:
        timer.finish(status=legacy_reject, request_id=request.request_id)
        return ChatSubmitResult(status=legacy_reject, ok=False)

    if c.use_unified_chat_api:
        gate = await assess_llm_submit_gate()
        if not gate.allowed:
            timer.finish(status=gate.status, request_id=request.request_id)
            return ChatSubmitResult(status=gate.status, ok=False)

        route_chain = await resolve_task_route_chain(task_name, explicit_model=request.model)
        task_route = route_chain[0]
        metadata = {
            "bot_id": request.bot_id,
            "group_id": request.group_id,
            "user_id": request.user_id,
            "request_id": request.request_id,
            "pg_session": use_pg_session,
            "mode": str(request.mode or "normal"),
            "task": task_name,
            "task_route": serialize_task_route(task_route),
            "task_route_chain": [serialize_task_route(item) for item in route_chain],
        }
        if task_route.resolved_model:
            metadata["resolved_model"] = task_route.resolved_model
        if task_route.provider_hint:
            metadata["provider_hint"] = task_route.provider_hint
        from pallas.product.llm.inference_params import chat_token_count_with_tools
        from pallas.product.llm.kernel import plan_direct_chat_stages
        from pallas.product.llm.tools.registry import tool_metadata_for_chat

        user_text = str(request.user_text or "").strip()
        if not user_text and messages:
            user_text = str(messages[-1].content or "")
        tool_meta = tool_metadata_for_chat(task=task_name, user_text=user_text)
        metadata.update(tool_meta)
        if task_name == "llm_chat":
            metadata["agent_stage_plan"] = plan_direct_chat_stages(tools_enabled=bool(tool_meta.get("tools_enabled")))
            metadata["tool_schema_count"] = len(tool_meta.get("tool_schemas") or [])
        metadata["token_count"] = chat_token_count_with_tools(
            request.token_count,
            tools_enabled=bool(tool_meta.get("tools_enabled")),
        )
        if request.temperature is not None:
            metadata["temperature"] = float(request.temperature)
        from pallas.product.llm.vision_content import extract_vision_message_payload, user_message_has_vision_content

        vision_payload = extract_vision_message_payload(user_text)
        metadata["has_image"] = user_message_has_vision_content(user_text)
        if vision_payload.image_urls:
            metadata["vision_image_urls"] = list(vision_payload.image_urls)
        if vision_payload.plain_text:
            metadata["vision_plain_text"] = vision_payload.plain_text
        summary_meta = runtime_state_summary_metadata(c)
        metadata["runtime_state_summary_enabled"] = can_write_runtime_state_summary(c)
        if summary_meta:
            metadata["session_summary"] = summary_meta
        if request.knowledge_retrieval_trace is not None:
            from pallas.product.llm.knowledge.registry import knowledge_metadata_payload

            metadata.update(knowledge_metadata_payload(request.knowledge_retrieval_trace, cfg=c))
        if request.hybrid_retrieval_trace is not None:
            metadata["hybrid_retrieval_trace"] = request.hybrid_retrieval_trace
        rewrite_meta = request.llm_rewrite_metadata
        if isinstance(rewrite_meta, dict):
            metadata.update({key: value for key, value in rewrite_meta.items() if value is not None and value != ""})
        from pallas.product.llm.runtime_debug import append_request_snapshot

        snapshot_id = append_request_snapshot(
            request_id=request.request_id,
            task=task_name,
            system_prompt=request.system_prompt,
            messages=[{"role": item.role, "content": item.content} for item in messages],
            metadata=metadata,
        )
        metadata.setdefault("runtime_debug", {})
        metadata["runtime_debug"]["request_snapshot_id"] = snapshot_id
        metadata["runtime_debug"]["replay_enabled"] = True
        metadata["runtime_debug"]["trace_level"] = "standard"
        chat_payload = {
            "session_id": request.session_id if not use_pg_session else request.request_id,
            "model": request.model,
            "system": request.system_prompt,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "metadata": metadata,
        }
        payload = build_llm_chat_capability_body(
            request_id=request.request_id,
            payload=chat_payload,
            bot_id=request.bot_id,
            group_id=request.group_id,
            user_id=request.user_id,
            session_id=chat_payload["session_id"],
            timeout_sec=c.chat_timeout_sec,
        )
    else:
        legacy_text = format_legacy_transcript(messages) if use_pg_session else messages[-1].content
        payload = {
            "session": request.request_id if use_pg_session else request.session_id,
            "text": legacy_text,
            "system_prompt": request.system_prompt,
            "model": request.model,
        }

    if is_repeater_llm_task(task_name):
        return await submit_repeater_chat_task(
            request,
            url=url,
            payload=payload,
            timer=timer,
            message_count=len(messages),
            cfg=c,
        )

    return await submit_llm_chat_task(
        request,
        url=url,
        payload=payload,
        timer=timer,
        message_count=len(messages),
        cfg=c,
    )


async def submit_repeater_chat_task(
    request: ChatSubmitRequest,
    *,
    url: str,
    payload: dict,
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
    response = None
    try:
        try:
            response = await HTTPXClient.post(url, json=payload, timeout=cfg.chat_timeout_sec)
        except Exception:
            logger.exception("llm submit_chat_task failed: url={}", url)
            timer.finish(status="request_failed", request_id=request.request_id)
            return ChatSubmitResult(status="request_failed", ok=False)
    finally:
        release_repeater_llm_slot(slot)
    timer.mark("http_post")

    if not response:
        timer.finish(status="empty_response", request_id=request.request_id)
        return ChatSubmitResult(status="empty_response", ok=False)

    try:
        body = response.json()
    except Exception:
        logger.warning("llm submit_chat_task invalid json: url={}", url)
        timer.finish(status="invalid_response", request_id=request.request_id)
        return ChatSubmitResult(status="invalid_response", ok=False)

    task_id = str(body.get("task_id") or body.get("id") or "")
    status = str(body.get("status") or ("processing" if task_id else "unknown"))
    ok = bool(task_id) or status in {"processing", "ok", "completed"}
    if ok:
        await refresh_repeater_group_cooldown(int(request.bot_id), int(request.group_id))
    timer.finish(status=status, request_id=request.request_id, message_count=message_count)
    return ChatSubmitResult(task_id=task_id, status=status, ok=ok)


async def submit_llm_chat_task(
    request: ChatSubmitRequest,
    *,
    url: str,
    payload: dict,
    timer: SlowPathTimer,
    message_count: int,
    cfg: LlmConfig,
) -> ChatSubmitResult:
    async with LlmChatGovernance(wait=False, cfg=cfg) as gov:
        if gov.skipped:
            timer.finish(status="skipped_busy", request_id=request.request_id)
            return ChatSubmitResult(status="busy", ok=False)
        try:
            response = await HTTPXClient.post(url, json=payload, timeout=cfg.chat_timeout_sec)
        except Exception:
            logger.exception("llm submit_chat_task failed: url={}", url)
            timer.finish(status="request_failed", request_id=request.request_id)
            return ChatSubmitResult(status="request_failed", ok=False)
    timer.mark("http_post")

    if not response:
        timer.finish(status="empty_response", request_id=request.request_id)
        return ChatSubmitResult(status="empty_response", ok=False)

    try:
        body = response.json()
    except Exception:
        logger.warning("llm submit_chat_task invalid json: url={}", url)
        timer.finish(status="invalid_response", request_id=request.request_id)
        return ChatSubmitResult(status="invalid_response", ok=False)

    task_id = str(body.get("task_id") or body.get("id") or "")
    status = str(body.get("status") or ("processing" if task_id else "unknown"))
    ok = bool(task_id) or status in {"processing", "ok", "completed"}
    timer.finish(status=status, request_id=request.request_id, message_count=message_count)
    return ChatSubmitResult(task_id=task_id, status=status, ok=ok)


def build_chat_messages(user_text: str, *, max_len: int = 4000) -> list[ChatCompletionMessage]:
    user_turn = format_user_turn(user_text, max_len=max_len)
    if not user_turn:
        return []
    return [ChatCompletionMessage(role="user", content=user_turn)]


async def delete_llm_chat_session(session_id: str, *, cfg: LlmConfig | None = None) -> bool:
    c = cfg or get_llm_config()
    base = llm_server_base_url(c)
    if c.use_unified_chat_api:
        url = f"{base}{c.unified_del_session_endpoint}/{session_id}"
    else:
        url = f"{base}{c.legacy_del_session_endpoint}/{session_id}"
    try:
        response = await HTTPXClient.delete(url, timeout=c.chat_timeout_sec)
    except Exception:
        logger.warning("delete_llm_chat_session failed: session={}", session_id)
        return False
    return bool(response) and response.status_code < 400
