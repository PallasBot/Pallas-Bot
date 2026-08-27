from __future__ import annotations

from typing import Any

from nonebot import logger

from pallas.core.platform.observability import SlowPathTimer, slow_path_threshold_ms
from pallas.core.shared.utils import HTTPXClient

from .budget import trim_messages_to_char_budget
from .config import LlmConfig, get_llm_config, llm_server_base_url
from .kernel.memory_governance import can_write_runtime_state_summary, runtime_state_summary_metadata
from .legacy_guard import assess_legacy_chat_submit
from .message_guard import format_user_turn
from .models import ChatCompletionMessage, ChatSubmitRequest, ChatSubmitResult
from .session_store import build_llm_chat_messages, is_llm_session_store_available
from .submit_gate import assess_llm_submit_gate
from .task_routing import resolve_submit_task_name, resolve_task_route_chain, serialize_task_route
from .vision_content import (
    VisionMessagePayload,
    extract_vision_message_payload,
    user_message_has_vision_content,
    vision_payload_from_segments,
)


async def resolve_chat_messages(
    request: ChatSubmitRequest,
    *,
    cfg: LlmConfig | None = None,
) -> list[ChatCompletionMessage]:
    c = cfg or get_llm_config()
    if request.prepared_messages is not None:
        messages = list(request.prepared_messages)
    elif is_llm_session_store_available() and request.bot_id is not None and request.user_id is not None:
        messages = await build_llm_chat_messages(
            int(request.bot_id),
            request.group_id,
            int(request.user_id),
            request.user_text,
            cfg=c,
            include_history=request.include_session_history,
            history_limit=request.session_history_limit,
            include_group_ambient=request.include_group_ambient_history,
        )
    else:
        user_turn = format_user_turn(request.user_text, max_len=c.user_message_max_len)
        messages = [ChatCompletionMessage(role="user", content=user_turn)] if user_turn else []
    if messages and request.style_user_hints:
        from pallas.product.llm.turn_style_layers import merge_style_hints_before_last_user

        messages = merge_style_hints_before_last_user(
            messages,
            list(request.style_user_hints),
            message_cls=ChatCompletionMessage,
        )
    return messages


async def _resolve_referenced_vision_payload(
    group_id: int,
    reply_to_id: int,
    *,
    referenced_message: dict[str, Any] | None = None,
    bot: Any | None = None,
) -> VisionMessagePayload | None:
    """按用户在群内引用(reply)的消息 id，解析出被引用消息里的图片与纯文字。

    优先用调用方预提取的 referenced_message（来源 event.reply.message，NoneBot 收包已填充，
    不依赖消息库回查或 get_msg）；未提供时查本地消息库，库中未命中再走 OneBot get_msg 兜底。
    找不到图片时返回 None。
    """
    # 第一优先：调用方已从 event.reply.message 预提取的引用图信息。
    pre_plain = ""
    pre_urls = (
        [u for u in (referenced_message or {}).get("image_urls") or [] if isinstance(u, str) and u.strip()]
        if referenced_message
        else []
    )
    if pre_urls:
        pre_plain = str((referenced_message or {}).get("plain_text") or "").strip()
        return VisionMessagePayload(has_image=True, image_urls=tuple(pre_urls), plain_text=pre_plain)

    from pallas.core.foundation.db import make_message_repository

    try:
        repo = make_message_repository()
        referenced = await repo.find_by_message_ids(int(group_id), [int(reply_to_id)])
    except Exception:
        referenced = []
    for message in referenced:
        payload = extract_vision_message_payload(str(getattr(message, "raw_message", "") or ""))
        if payload is not None and payload.has_image:
            return payload

    if bot is not None and hasattr(bot, "call_api"):
        try:
            resp = await bot.call_api("get_msg", message_id=int(reply_to_id))
        except Exception as exc:
            logger.debug("get_msg fallback failed for message [{}] in group [{}]: {}", reply_to_id, group_id, exc)
            return None
        data = resp if isinstance(resp, dict) else {}
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        message_segments = inner.get("message") if isinstance(inner, dict) else None
        payload = vision_payload_from_segments(message_segments)
        if not payload.image_urls:
            return None
        return payload
    return None


async def submit_chat_task(
    request: ChatSubmitRequest,
    *,
    cfg: LlmConfig | None = None,
    bot: Any | None = None,
) -> ChatSubmitResult:
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

    if request.prepared_messages is None and c.llm_chat_char_budget > 0:
        messages = trim_messages_to_char_budget(
            messages,
            system_prompt=request.system_prompt,
            budget_chars=c.llm_chat_char_budget,
        )
        timer.mark("trim_budget")

    use_pg_session = is_llm_session_store_available() and request.bot_id is not None and request.user_id is not None
    task_name = resolve_submit_task_name(request.task, request.mode)

    legacy_reject = assess_legacy_chat_submit(c)
    if legacy_reject:
        timer.finish(status=legacy_reject, request_id=request.request_id)
        return ChatSubmitResult(status=legacy_reject, ok=False)

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
    from pallas.product.llm.assembler import assemble_tool_bundle
    from pallas.product.llm.inference_params import resolve_task_token_budget

    user_text = str(request.user_text or "").strip()
    if not user_text and messages:
        user_text = str(messages[-1].content or "")
    tool_meta = assemble_tool_bundle(
        task=task_name,
        user_text=user_text,
        tool_metadata=request.tool_metadata,
        bot_id=request.bot_id,
        group_id=request.group_id,
        user_id=request.user_id,
    )
    metadata.update(tool_meta)
    metadata["token_count"] = resolve_task_token_budget(
        task_name,
        tools_enabled=bool(tool_meta.get("tools_enabled")),
        requested=request.token_count,
    )
    if request.temperature is not None:
        metadata["temperature"] = float(request.temperature)

    vision_payload = extract_vision_message_payload(user_text)
    metadata["has_image"] = user_message_has_vision_content(user_text)
    if vision_payload.image_urls:
        metadata["vision_image_urls"] = list(vision_payload.image_urls)
    if vision_payload.plain_text:
        metadata["vision_plain_text"] = vision_payload.plain_text
    # 引用(reply)带图消息时，被引用的图不在当前消息文本里，需按 reply_to_message_id
    # 查原消息并把其中的图片并入视觉上下文，否则「描述一下这张图」会落回历史图。
    reply_to_id = getattr(request, "reply_to_message_id", None)
    referenced_message = getattr(request, "referenced_message", None) or None
    if (reply_to_id is not None or referenced_message) and request.group_id is not None:
        referenced = await _resolve_referenced_vision_payload(
            int(request.group_id),
            int(reply_to_id or 0),
            referenced_message=referenced_message,
            bot=bot,
        )
        if referenced is not None:
            existing = list(metadata.get("vision_image_urls") or [])
            merged = existing + [url for url in referenced.image_urls if url not in existing]
            if merged:
                metadata["vision_image_urls"] = merged
                metadata["has_image"] = True
            if referenced.plain_text and "vision_plain_text" not in metadata:
                metadata["vision_plain_text"] = referenced.plain_text
    timeline_images = [
        {
            "speaker": str(item.get("speaker") or "").strip(),
            "text": str(item.get("text") or "").strip(),
            "url": str(item.get("url") or "").strip(),
        }
        for item in request.group_timeline_images[:3]
        if isinstance(item, dict)
    ]
    if timeline_images:
        metadata["group_timeline_images"] = timeline_images
    from pallas.product.llm.providers_store import (
        find_provider,
        provider_capabilities,
        provider_model_effort,
        resolve_endpoint_for_task,
    )

    endpoint = resolve_endpoint_for_task(task_name)
    if endpoint is not None:
        row = find_provider(endpoint.provider_id)
        caps = provider_capabilities(row, endpoint.model) if row else list(endpoint.capabilities)
        if caps:
            metadata["provider_capabilities"] = caps
        effort = provider_model_effort(row, endpoint.model) if row else endpoint.model_effort
        if effort:
            metadata["model_effort"] = effort
        metadata["provider_hint"] = metadata.get("provider_hint") or endpoint.provider_id
    summary_meta = runtime_state_summary_metadata(c)
    metadata["runtime_state_summary_enabled"] = can_write_runtime_state_summary(c)
    if summary_meta:
        metadata["session_summary"] = summary_meta
    if request.knowledge_retrieval_trace is not None:
        from pallas.product.llm.knowledge.registry import knowledge_metadata_payload

        metadata.update(knowledge_metadata_payload(request.knowledge_retrieval_trace, cfg=c))
    if request.hybrid_retrieval_trace is not None:
        metadata["hybrid_retrieval_trace"] = request.hybrid_retrieval_trace
        metadata["retrieval_mode"] = request.hybrid_retrieval_trace.get("retrieve_mode")
    rewrite_meta = request.llm_rewrite_metadata
    if isinstance(rewrite_meta, dict):
        metadata.update({key: value for key, value in rewrite_meta.items() if value is not None and value != ""})
    from pallas.product.llm.runtime_debug import append_request_snapshot

    message_dicts = [{"role": item.role, "content": item.content} for item in messages]
    snapshot_id = append_request_snapshot(
        request_id=request.request_id,
        task=task_name,
        system_prompt=request.system_prompt,
        messages=message_dicts,
        metadata=metadata,
    )
    metadata.setdefault("runtime_debug", {})
    metadata["runtime_debug"]["request_snapshot_id"] = snapshot_id
    metadata["runtime_debug"]["replay_enabled"] = True
    metadata["runtime_debug"]["trace_level"] = "standard"
    from pallas.product.llm.kernel_runner import submit_kernel_llm_chat_task

    return await submit_kernel_llm_chat_task(
        request,
        system_prompt=request.system_prompt,
        messages=message_dicts,
        metadata=metadata,
        timer=timer,
        message_count=len(messages),
        cfg=c,
    )


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
        logger.warning("LLM chat session deletion failed for session [{}]", session_id)
        return False
    return bool(response) and response.status_code < 400
