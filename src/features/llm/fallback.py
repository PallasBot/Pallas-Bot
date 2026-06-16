"""接话语料 miss 时异步提交 LLM 生成（默认关）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nonebot import logger
from ulid import ULID

from src.features.llm.client import submit_chat_task
from src.features.llm.config import get_llm_config
from src.features.llm.models import ChatSubmitRequest
from src.features.llm.persona_context import build_persona_llm_context
from src.foundation.config import TaskManager
from src.platform.ai_callback.task_types import REPEATER_FALLBACK_TASK_TYPE

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent


async def maybe_submit_repeater_llm_fallback(event: GroupMessageEvent, *, user_text: str) -> bool:
    cfg = get_llm_config()
    if not cfg.llm_fallback_enabled or not cfg.llm_chat_enabled:
        return False

    text = (user_text or "").strip()
    if not text or "[CQ:" in text:
        return False
    if len(text) > cfg.user_message_max_len:
        text = text[: cfg.user_message_max_len].strip()
    if not text:
        return False

    group_id = int(event.group_id)
    user_id = int(event.user_id)
    bot_id = int(event.self_id)
    session_id = f"repeater_fb_{bot_id}_{group_id}_{user_id}"

    try:
        bundle, temperature, token_count = await build_persona_llm_context(
            bot_id,
            group_id,
            text,
            mode="normal",
            purpose="fallback",
        )
        system_prompt = bundle.system.strip()
    except Exception:
        logger.exception("repeater llm fallback compile_persona_prompt failed group={}", group_id)
        return False
    if not system_prompt:
        return False

    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id,
            "task_type": REPEATER_FALLBACK_TASK_TYPE,
            "start_time": time.time(),
        },
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=text,
            system_prompt=system_prompt,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            mode="normal",
            task="repeater_fallback",
            token_count=token_count,
            temperature=temperature,
        ),
        cfg=cfg,
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
        logger.debug(
            "repeater llm fallback submit skipped: status={} group={} user={}",
            result.status,
            group_id,
            user_id,
        )
        return False

    logger.info(
        "repeater llm fallback queued: request_id={} group={} user={} text_len={}",
        request_id,
        group_id,
        user_id,
        len(text),
    )
    return True
