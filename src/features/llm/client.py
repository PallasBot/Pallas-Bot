from __future__ import annotations

from nonebot import logger

from src.shared.utils import HTTPXClient

from .config import LlmConfig, get_llm_config, llm_server_base_url
from .message_guard import format_user_turn
from .models import ChatCompletionMessage, ChatSubmitRequest, ChatSubmitResult


def chat_endpoint_path(cfg: LlmConfig | None = None) -> str:
    c = cfg or get_llm_config()
    if c.use_unified_chat_api:
        return c.unified_chat_endpoint
    return c.legacy_chat_endpoint


async def submit_chat_task(request: ChatSubmitRequest, *, cfg: LlmConfig | None = None) -> ChatSubmitResult:
    c = cfg or get_llm_config()
    user_turn = format_user_turn(request.user_text, max_len=c.user_message_max_len)
    if not user_turn:
        return ChatSubmitResult(status="empty_user_message", ok=False)

    base = llm_server_base_url(c)
    endpoint = chat_endpoint_path(c)
    url = f"{base}{endpoint}/{request.request_id}"

    if c.use_unified_chat_api:
        payload = {
            "session_id": request.session_id,
            "model": request.model,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": user_turn}],
            "metadata": {
                "bot_id": request.bot_id,
                "group_id": request.group_id,
                "request_id": request.request_id,
            },
        }
    else:
        payload = {
            "session": request.session_id,
            "text": user_turn,
            "system_prompt": request.system_prompt,
            "model": request.model,
        }

    try:
        response = await HTTPXClient.post(url, json=payload, timeout=c.chat_timeout_sec)
    except Exception:
        logger.exception("llm submit_chat_task failed: url={}", url)
        return ChatSubmitResult(status="request_failed", ok=False)

    if not response:
        return ChatSubmitResult(status="empty_response", ok=False)

    try:
        body = response.json()
    except Exception:
        logger.warning("llm submit_chat_task invalid json: url={}", url)
        return ChatSubmitResult(status="invalid_response", ok=False)

    task_id = str(body.get("task_id") or body.get("id") or "")
    status = str(body.get("status") or ("processing" if task_id else "unknown"))
    ok = bool(task_id) or status in {"processing", "ok", "completed"}
    return ChatSubmitResult(task_id=task_id, status=status, ok=ok)


def build_chat_messages(user_text: str, *, max_len: int = 4000) -> list[ChatCompletionMessage]:
    user_turn = format_user_turn(user_text, max_len=max_len)
    if not user_turn:
        return []
    return [ChatCompletionMessage(role="user", content=user_turn)]
