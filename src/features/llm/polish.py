"""接话命中语料时的 LLM 轻改写（默认关，异步 callback 回发）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nonebot import logger
from ulid import ULID

from src.features.llm.client import submit_chat_task
from src.features.llm.config import get_llm_config
from src.features.llm.models import ChatSubmitRequest
from src.features.persona.compile_persona_prompt import compile_persona_prompt_for
from src.foundation.config import TaskManager

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

REPEATER_POLISH_TASK_TYPE = "repeater_polish"

_POLISH_USER_PREFIX = "【候选回复】"
_POLISH_USER_SUFFIX = "\n请按牛格轻改写以上回复，保持原意，只输出一句。"

_LENGTH_POLISH_HINTS: dict[str, str] = {
    "short": "改写后保持短句（1-2 句）",
    "medium": "长度适中（2-3 句）",
    "long": "可略展开但仍以一句口语为主",
}


async def build_polish_style_suffix(bot_id: int, group_id: int) -> str:
    from src.features.persona.compile_group_style import compile_group_style_snapshot
    from src.foundation.db import make_group_config_repository

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


def build_polish_user_text(candidate: str, *, style_suffix: str = "") -> str:
    text = (candidate or "").strip()
    if not text:
        return ""
    suffix = (style_suffix or "").strip()
    tail = f"{suffix}{_POLISH_USER_SUFFIX}" if suffix else _POLISH_USER_SUFFIX
    return f"{_POLISH_USER_PREFIX}{text}{tail}"


async def maybe_submit_repeater_llm_polish(
    event: GroupMessageEvent,
    *,
    candidate_text: str,
) -> bool:
    cfg = get_llm_config()
    if not cfg.llm_polish_enabled or not cfg.llm_chat_enabled:
        return False

    candidate = (candidate_text or "").strip()
    if not candidate or "[CQ:" in candidate:
        return False

    group_id = int(event.group_id)
    user_id = int(event.user_id)
    bot_id = int(event.self_id)

    user_text = build_polish_user_text(candidate, style_suffix=await build_polish_style_suffix(bot_id, group_id))
    if not user_text:
        return False

    session_id = f"repeater_pl_{bot_id}_{group_id}_{user_id}"

    try:
        bundle = await compile_persona_prompt_for(bot_id, group_id, mode="normal")
        system_prompt = bundle.system.strip()
    except Exception:
        logger.exception("repeater llm polish compile_persona_prompt failed group={}", group_id)
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
            "task_type": REPEATER_POLISH_TASK_TYPE,
            "fallback_text": candidate,
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
            token_count=120,
        ),
        cfg=cfg,
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
        logger.debug(
            "repeater llm polish submit skipped: status={} group={} user={}",
            result.status,
            group_id,
            user_id,
        )
        return False

    logger.info(
        "repeater llm polish queued: request_id={} group={} user={} candidate_len={}",
        request_id,
        group_id,
        user_id,
        len(candidate),
    )
    return True
