"""接语料未命中时异步智能生成，默认关。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nonebot import logger
from ulid import ULID

from pallas.core.foundation.config import TaskManager
from pallas.core.platform.ai_callback.task_types import REPEATER_FALLBACK_TASK_TYPE
from pallas.product.llm.client import submit_chat_task
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.repeater_persona_context import build_repeater_llm_persona_context
from pallas.product.llm.task_metrics import record_bot_llm_task

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent


async def build_fallback_system_prompt(
    bot_id: int,
    group_id: int,
    plain_text: str,
    *,
    user_id: int | None = None,
    feedback_suffix: str = "",
) -> tuple[str, float | None, int | None, dict | None]:
    bundle = await build_repeater_llm_persona_context(
        bot_id,
        group_id,
        plain_text,
        purpose="fallback_lite",
        user_id=user_id,
        feedback_suffix=feedback_suffix,
    )
    if bundle is None:
        return "", None, None, None
    return bundle.system_prompt, bundle.temperature, bundle.token_count, bundle.llm_rewrite_metadata


async def build_fallback_expression_suffix(group_id: int) -> str:
    from pallas.core.foundation.db import make_group_config_repository
    from pallas.product.persona.expression_habits import build_expression_habits_suffix

    group_config = await make_group_config_repository().get(int(group_id))
    profile = getattr(group_config, "style_profile", None) if group_config is not None else None
    return build_expression_habits_suffix(profile if isinstance(profile, dict) else None)


async def maybe_submit_repeater_llm_fallback(
    event: GroupMessageEvent,
    *,
    user_text: str,
    reply_mode: str = "normal",
) -> bool:
    if event.is_tome():
        return False

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

    from pallas.product.llm.feedback_chat_hint import load_repeater_feedback_system_suffix

    feedback_hint = await load_repeater_feedback_system_suffix(group_id=group_id, user_text=text)
    expression_suffix = await build_fallback_expression_suffix(group_id)
    system_prompt, temperature, token_count, rewrite_metadata = await build_fallback_system_prompt(
        bot_id,
        group_id,
        text,
        user_id=user_id,
        feedback_suffix=feedback_hint,
    )
    if not system_prompt:
        return False

    prompt_user = text
    if expression_suffix:
        prompt_user = f"{text}\n{expression_suffix}"

    session_id = f"repeater_fb_{bot_id}_{group_id}_{user_id}"
    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id,
            "task_type": REPEATER_FALLBACK_TASK_TYPE,
            "user_text": text,
            "reply_mode": str(reply_mode or "normal"),
            "start_time": time.time(),
        },
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=prompt_user,
            system_prompt=system_prompt,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            mode="normal",
            task="repeater_fallback",
            token_count=token_count,
            temperature=temperature,
            llm_rewrite_metadata=rewrite_metadata,
        ),
        cfg=cfg,
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
        record_bot_llm_task(REPEATER_FALLBACK_TASK_TYPE, "submit_skip")
        logger.debug(
            "repeater llm fallback submit skipped: status={} group={} user={}",
            result.status,
            group_id,
            user_id,
        )
        return False

    record_bot_llm_task(REPEATER_FALLBACK_TASK_TYPE, "submit_ok")
    logger.info(
        "repeater llm fallback queued: request_id={} group={} user={} text_len={}",
        request_id,
        group_id,
        user_id,
        len(text),
    )
    return True
