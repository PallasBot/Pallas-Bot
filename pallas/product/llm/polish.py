"""接话命中语料时异步润色，默认关。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nonebot import logger
from ulid import ULID

from pallas.core.foundation.config import TaskManager
from pallas.core.platform.ai_callback.task_types import REPEATER_POLISH_TASK_TYPE
from pallas.product.llm.client import submit_chat_task
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.repeater_persona_context import build_repeater_llm_persona_context
from pallas.product.llm.task_metrics import record_bot_llm_task

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

_POLISH_USER_PREFIX = "【候选回复】"
_POLISH_USER_SUFFIX = "\n请轻顺口气，像群友接话；保持原意，只输出一句。"
_POLISH_MEDIUM_USER_SUFFIX = "\n可近义改写并微调长短，仍锚定原意；禁止另起话题、勿扩写成完整答复。只输出一句。"

_LENGTH_POLISH_HINTS: dict[str, str] = {
    "short": "改写后保持短句（1-2 句）",
    "medium": "长度适中（2-3 句）",
    "long": "可略展开但仍以一句口语为主",
}


async def build_polish_style_suffix(bot_id: int, group_id: int) -> str:
    from pallas.core.foundation.db import make_group_config_repository
    from pallas.product.persona.compile_group_style import compile_group_style_snapshot

    group_config = await make_group_config_repository().get(int(group_id))
    profile = getattr(group_config, "style_profile", None) if group_config is not None else None
    snapshot = compile_group_style_snapshot(profile if isinstance(profile, dict) else None)
    if not snapshot.get("ready"):
        return ""

    signals = snapshot.get("signals") or {}
    hints = snapshot.get("hints") or []
    parts: list[str] = []
    length_pref = str(signals.get("length_pref") or "").strip()
    length_hint = _LENGTH_POLISH_HINTS.get(length_pref)
    if length_hint:
        parts.append(length_hint)
    if hints:
        parts.append("群习惯：" + "、".join(str(item) for item in hints[:3]))
    if not parts:
        return ""
    _ = bot_id
    return "\n【群风格参考】" + "；".join(parts) + "。"


def build_polish_user_text(candidate: str, *, style_suffix: str = "", intensity: str = "light") -> str:
    text = (candidate or "").strip()
    if not text:
        return ""
    suffix = (style_suffix or "").strip()
    instruction = _POLISH_MEDIUM_USER_SUFFIX if intensity == "medium" else _POLISH_USER_SUFFIX
    tail = f"{suffix}{instruction}" if suffix else instruction
    return f"{_POLISH_USER_PREFIX}{text}{tail}"


async def maybe_submit_repeater_llm_polish(
    event: GroupMessageEvent,
    *,
    candidate_text: str,
    trigger_user_text: str = "",
    reply_mode: str = "normal",
    force_for_cue: bool = False,
    intensity: str = "light",
) -> bool:
    if event.is_tome():
        return False

    cfg = get_llm_config()
    if not cfg.llm_chat_enabled:
        return False
    if not cfg.llm_polish_enabled and not force_for_cue:
        return False
    if force_for_cue and not (cfg.llm_polish_enabled or cfg.llm_select_enabled or cfg.llm_polish_lite_enabled):
        return False

    candidate = (candidate_text or "").strip()
    from pallas.product.llm.corpus_contamination import is_llm_learning_safe

    if not candidate or not is_llm_learning_safe(candidate):
        return False

    group_id = int(event.group_id)
    user_id = int(event.user_id)
    bot_id = int(event.self_id)

    polish_intensity = "medium" if force_for_cue or intensity == "medium" else "light"
    user_text = build_polish_user_text(
        candidate,
        style_suffix=await build_polish_style_suffix(bot_id, group_id),
        intensity=polish_intensity,
    )
    if not user_text:
        return False

    session_id = f"repeater_pl_{bot_id}_{group_id}_{user_id}"
    trigger_plain = str(trigger_user_text or candidate).strip()

    try:
        from pallas.product.llm.feedback_chat_hint import load_repeater_feedback_system_suffix

        feedback_hint = await load_repeater_feedback_system_suffix(group_id=group_id, user_text=trigger_plain)
        persona_bundle = await build_repeater_llm_persona_context(
            bot_id,
            group_id,
            trigger_plain or candidate,
            purpose="polish",
            user_id=user_id,
            feedback_suffix=feedback_hint,
        )
        if persona_bundle is None or not persona_bundle.system_prompt:
            return False
        system_prompt = persona_bundle.system_prompt
        temperature = persona_bundle.temperature
        token_count = persona_bundle.token_count
        rewrite_metadata = persona_bundle.llm_rewrite_metadata
    except Exception:
        logger.exception("repeater llm polish compile_persona_prompt failed group={}", group_id)
        return False

    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id,
            "task_type": REPEATER_POLISH_TASK_TYPE,
            "user_text": str(trigger_user_text or "").strip(),
            "fallback_text": candidate,
            "reply_mode": str(reply_mode or "normal"),
            "start_time": time.time(),
        },
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=user_text,
            system_prompt=system_prompt,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            mode="normal",
            task="repeater_polish",
            token_count=token_count,
            temperature=temperature,
            llm_rewrite_metadata=rewrite_metadata,
        ),
        cfg=cfg,
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
        record_bot_llm_task(REPEATER_POLISH_TASK_TYPE, "submit_skip")
        logger.debug(
            "repeater llm polish submit skipped: status={} group={} user={}",
            result.status,
            group_id,
            user_id,
        )
        return False

    record_bot_llm_task(REPEATER_POLISH_TASK_TYPE, "submit_ok")
    logger.info(
        "repeater llm polish queued: request_id={} group={} user={} candidate_len={}",
        request_id,
        group_id,
        user_id,
        len(candidate),
    )
    return True
