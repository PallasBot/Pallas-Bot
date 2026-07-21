"""接话语料命中时偶尔轻顺口气（select 主路径下的增味分支）。"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

from nonebot import logger
from ulid import ULID

from pallas.core.foundation.config import TaskManager
from pallas.core.platform.ai_callback.task_types import REPEATER_POLISH_LITE_TASK_TYPE
from pallas.product.llm.client import submit_chat_task
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.repeater_persona_context import build_repeater_llm_persona_context
from pallas.product.llm.task_metrics import record_bot_llm_task

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent


def should_polish_lite_sample(
    bot_id: int,
    group_id: int,
    message_id: int,
    *,
    sample_rate: float,
) -> bool:
    rate = max(0.0, min(1.0, float(sample_rate)))
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    seed = int(bot_id) ^ int(group_id) ^ int(message_id)
    rng = random.Random(seed)
    return rng.random() < rate


def build_polish_lite_user_text(user_text: str, candidate_text: str) -> str:
    return build_polish_lite_user_text_with_suffix(user_text, candidate_text, style_suffix="")


def build_polish_lite_user_text_with_suffix(user_text: str, candidate_text: str, *, style_suffix: str = "") -> str:
    from pallas.product.llm.expressor import build_expressor_user_text

    return build_expressor_user_text(
        user_text=user_text,
        raw_reply=candidate_text,
        reason="",
        style_suffix=style_suffix,
    )


async def build_polish_lite_style_suffix(group_id: int) -> str:
    from pallas.core.foundation.db import make_group_config_repository
    from pallas.product.persona.expression_habits import build_expression_habits_suffix

    group_config = await make_group_config_repository().get(int(group_id))
    profile = getattr(group_config, "style_profile", None) if group_config is not None else None
    return build_expression_habits_suffix(profile if isinstance(profile, dict) else None)


async def maybe_submit_repeater_llm_polish_lite(
    event: GroupMessageEvent,
    *,
    user_text: str,
    candidate_text: str,
    reply_mode: str = "normal",
) -> bool:
    cfg = get_llm_config()
    if not cfg.llm_polish_lite_enabled or not cfg.llm_chat_enabled:
        return False

    candidate = str(candidate_text or "").strip()
    plain = str(user_text or "").strip()
    from pallas.product.llm.corpus_contamination import is_llm_learning_safe

    if not candidate or not plain or not is_llm_learning_safe(candidate) or "[CQ:" in plain:
        return False

    group_id = int(event.group_id)
    user_id = int(event.user_id)
    bot_id = int(event.self_id)
    prompt_user = build_polish_lite_user_text_with_suffix(
        plain,
        candidate,
        style_suffix=await build_polish_lite_style_suffix(group_id),
    )
    if not prompt_user:
        return False

    from pallas.product.llm.feedback_chat_hint import load_repeater_feedback_system_suffix

    feedback_hint = await load_repeater_feedback_system_suffix(group_id=group_id, user_text=plain)
    persona_bundle = await build_repeater_llm_persona_context(
        bot_id,
        group_id,
        plain,
        purpose="polish_lite",
        mode=str(reply_mode or "normal"),
        user_id=user_id,
        feedback_suffix=feedback_hint,
    )
    if persona_bundle is None or not persona_bundle.system_prompt:
        return False

    session_id = f"repeater_pll_{bot_id}_{group_id}_{user_id}"
    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id,
            "task_type": REPEATER_POLISH_LITE_TASK_TYPE,
            "user_text": plain,
            "fallback_text": candidate,
            "reply_mode": str(reply_mode or "normal"),
            "reply_max_length": 36,
            "start_time": time.time(),
        },
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=prompt_user,
            system_prompt=persona_bundle.system_prompt,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            mode="normal",
            task="repeater_polish_lite",
            token_count=persona_bundle.token_count,
            temperature=persona_bundle.temperature,
            llm_rewrite_metadata=persona_bundle.llm_rewrite_metadata,
        ),
        cfg=cfg,
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
        record_bot_llm_task(REPEATER_POLISH_LITE_TASK_TYPE, "submit_skip")
        logger.debug(
            "repeater llm polish_lite submit skipped: status={} group={} user={}",
            result.status,
            group_id,
            user_id,
        )
        return False

    record_bot_llm_task(REPEATER_POLISH_LITE_TASK_TYPE, "submit_ok")
    logger.info(
        "repeater llm polish_lite queued: request_id={} group={} user={} candidate_len={}",
        request_id,
        group_id,
        user_id,
        len(candidate),
    )
    return True


async def maybe_submit_repeater_corpus_llm(
    event: GroupMessageEvent,
    *,
    user_text: str,
    candidates: list[str],
    candidate_text: str,
    reply_mode: str = "normal",
) -> bool:
    """语料 hit：接话 cue 时优先中等润色；否则 select / lite / polish。"""
    cfg = get_llm_config()
    from packages.repeater.opportunity_gate import looks_like_reply_cue
    from pallas.product.llm.corpus_contamination import is_llm_learning_safe

    pool = [str(item).strip() for item in candidates if str(item).strip() and is_llm_learning_safe(str(item))]
    candidate = str(candidate_text or "").strip()
    if not is_llm_learning_safe(candidate):
        candidate = ""

    cue = looks_like_reply_cue(user_text)
    if cue and candidate and len(pool) >= 2:
        from pallas.product.llm.polish import maybe_submit_repeater_llm_polish

        if await maybe_submit_repeater_llm_polish(
            event,
            candidate_text=candidate,
            trigger_user_text=user_text,
            reply_mode=reply_mode,
            force_for_cue=True,
            intensity="medium",
        ):
            return True

    if cfg.llm_polish_lite_enabled and candidate and pool:
        if should_polish_lite_sample(
            int(event.self_id),
            int(event.group_id),
            int(event.message_id),
            sample_rate=cfg.llm_polish_lite_sample_rate,
        ):
            if await maybe_submit_repeater_llm_polish_lite(
                event,
                user_text=user_text,
                candidate_text=candidate,
                reply_mode=reply_mode,
            ):
                return True

    if len(pool) >= 2 and cfg.llm_select_enabled:
        from pallas.product.llm.select import maybe_submit_repeater_llm_select

        if await maybe_submit_repeater_llm_select(
            event,
            user_text=user_text,
            candidates=pool,
            fallback_text=candidate,
            reply_mode=reply_mode,
        ):
            return True

    if candidate and cfg.llm_polish_enabled:
        from pallas.product.llm.polish import maybe_submit_repeater_llm_polish

        if await maybe_submit_repeater_llm_polish(
            event,
            candidate_text=candidate,
            trigger_user_text=user_text,
            reply_mode=reply_mode,
        ):
            return True

    return False
