"""会话历史摘要压缩：存储窗口内历史超阈值时，由主仓 LLM 生成摘要回插。

配合 storage_window（存储放宽）与 list_user_llm_messages 的摘要保留，
长对话以「摘要 + 最近 N 条」的形式进入模型，而非全量原文。
"""

from __future__ import annotations

import asyncio
from typing import Any

from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.inference_params import task_token_budget
from pallas.product.llm.kernel.memory_governance import can_write_runtime_state_summary
from pallas.product.llm.memory.rate_limit import WriteCooldown
from pallas.product.llm.provider_client import complete_chat_message
from pallas.product.llm.session_store import (
    compact_user_llm_history_with_summary,
    is_llm_session_store_available,
    list_user_llm_messages,
)

_summary_mark = "【此前对话摘要】"
_in_flight: set[tuple[int, int, int]] = set()
_last_compact_at = WriteCooldown()

_SESSION_SUMMARY_SYSTEM = """你是群聊对话摘要助手。把用户与机器人的一段聊天历史压缩成一条不超过 120 字的中文摘要。

要求：
- 保留话题脉络、已达成结论、对方的稳定偏好、承诺或待办；丢弃寒暄、复读、无关闲聊。
- 不记录个人隐私、辱骂、机器指令；不编造没有出现的信息。
- 只输出摘要正文，不要标题、列表或解释。"""


def _summary_messages(history: list[Any]) -> str:
    lines: list[str] = []
    for turn in history:
        role = str(getattr(turn, "role", "") or "").strip()
        content = str(getattr(turn, "content", "") or "").strip()
        if not content or _summary_mark in content:
            continue
        label = "你" if role == "assistant" else "对方"
        lines.append(f"{label}：{content[:240]}")
    return "\n".join(lines)


def _compact_ok(bot_id: int, group_id: int, user_id: int, *, cooldown_sec: int) -> bool:
    key = (int(bot_id), int(group_id) if group_id is not None else 0, int(user_id))
    return _last_compact_at.ok(key, cooldown_sec)


def _mark_compacted(bot_id: int, group_id: int, user_id: int) -> None:
    key = (int(bot_id), int(group_id) if group_id is not None else 0, int(user_id))
    _last_compact_at.mark(key)


async def maybe_compact_session_history(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    cfg: LlmConfig | None = None,
) -> bool:
    """存储窗口内历史超阈值时压缩：生成摘要 + 保留最近 N 条原文。"""
    c = cfg or get_llm_config()
    if not can_write_runtime_state_summary(c) or not is_llm_session_store_available():
        return False
    if not user_id:
        return False
    threshold = max(8, int(c.llm_session_summary_threshold))
    keep = max(4, min(int(c.llm_session_summary_keep_messages), int(c.llm_session_user_window)))
    bid, uid = int(bot_id), int(user_id)
    gid = int(group_id) if group_id is not None else None
    key = (bid, gid or 0, uid)
    if key in _in_flight:
        return False
    if not _compact_ok(bid, gid, uid, cooldown_sec=int(c.llm_session_summary_cooldown_sec)):
        return False
    history = await list_user_llm_messages(bid, gid, uid, limit=int(c.llm_session_user_storage_window), cfg=c)
    user_turns = [turn for turn in history if str(getattr(turn, "role", "") or "") == "user"]
    if len(user_turns) < threshold:
        return False
    _in_flight.add(key)
    try:
        transcript = _summary_messages(history)
        if not transcript:
            return False
        try:
            message = await complete_chat_message(
                [{"role": "system", "content": _SESSION_SUMMARY_SYSTEM}, {"role": "user", "content": transcript}],
                model="",
                options={
                    "temperature": 0.2,
                    "max_tokens": task_token_budget("memory_extract"),
                },
                task="memory_extract",
                cfg=c,
            )
        except Exception as exc:
            logger.warning("Session summary generation failed for bot [{}] and user [{}]: [{}]", bid, uid, exc)
            return False
        summary = str(message.get("content") or "") if isinstance(message, dict) else ""
        summary = " ".join(summary.split()).strip()
        if not summary or _summary_mark in summary:
            return False
        ok = await compact_user_llm_history_with_summary(
            bid,
            gid,
            uid,
            summary,
            keep_messages=keep,
            cfg=c,
        )
        if ok:
            _mark_compacted(bid, gid, uid)
            logger.info(
                "Session history compacted for bot [{}], group [{}], user [{}]: kept [{}]",
                bid,
                gid or "-",
                uid,
                keep,
            )
            return True
        return False
    finally:
        _in_flight.discard(key)


def schedule_session_summary(*, bot_id: int, group_id: int | None, user_id: int, cfg: LlmConfig | None = None) -> None:
    c = cfg or get_llm_config()
    if not can_write_runtime_state_summary(c) or not user_id:
        return
    try:
        asyncio.get_running_loop().create_task(
            maybe_compact_session_history(bot_id=bot_id, group_id=group_id, user_id=user_id, cfg=c),
            name=f"session_summary:{bot_id}:{group_id or 0}:{user_id}",
        )
    except RuntimeError:
        return


def clear_session_summary_state_for_tests() -> None:
    _in_flight.clear()
    _last_compact_at.clear()


def session_summary_status_snapshot() -> dict[str, Any]:
    return {
        "in_flight": len(_in_flight),
        "compacted_keys": _last_compact_at.tracked(),
    }
