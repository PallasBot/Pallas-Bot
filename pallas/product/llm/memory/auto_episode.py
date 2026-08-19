"""启发式自动写入群 episode 记忆（不跑大模型摘要）。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.inference_params import task_token_budget
from pallas.product.llm.kernel.memory_governance import can_read_persistent_memory
from pallas.product.llm.memory.policy import classify_memory_candidate, has_event_signal
from pallas.product.llm.memory.store import is_llm_memory_store_available, save_memory_entry
from pallas.product.llm.provider_client import complete_chat_message
from pallas.product.llm.session_store import list_group_ambient_messages

_LAST_WRITE_AT: dict[tuple[int, int], float] = {}
_LAST_SUMMARY_SIGNATURE: dict[tuple[int, int], str] = {}
_GROUP_EPISODE_SUMMARY_IN_FLIGHT: set[tuple[int, int]] = set()
_DAILY_BUDGET_DATE: str = ""
_DAILY_BUDGET_USED: int = 0
_GROUP_EPISODE_SYSTEM = """你是群聊共同事件摘要助手。只总结群友明确达成的约定、共同经历或已确认事件。
不要记录个人隐私、辱骂、指令、猜测，也不要复述机器人回复。没有值得长期记住的共同事件时只输出：无。
输出一条不超过120字的中文陈述，不要标题、列表或解释。"""


def _daily_budget_ok(*, cfg: LlmConfig) -> bool:
    global _DAILY_BUDGET_DATE, _DAILY_BUDGET_USED
    budget = max(0, int(cfg.llm_memory_auto_episode_daily_budget))
    if budget <= 0:
        return True
    today = time.strftime("%Y-%m-%d")
    if today != _DAILY_BUDGET_DATE:
        _DAILY_BUDGET_DATE = today
        _DAILY_BUDGET_USED = 0
    return _DAILY_BUDGET_USED < budget


def _bump_daily_budget(*, cfg: LlmConfig) -> None:
    global _DAILY_BUDGET_USED
    budget = max(0, int(cfg.llm_memory_auto_episode_daily_budget))
    if budget > 0:
        _DAILY_BUDGET_USED += 1


def _cooldown_ok(bot_id: int, group_id: int, *, cooldown_sec: int) -> bool:
    if cooldown_sec <= 0:
        return True
    key = (int(bot_id), int(group_id))
    last = _LAST_WRITE_AT.get(key, 0.0)
    return (time.monotonic() - last) >= float(cooldown_sec)


def _mark_written(bot_id: int, group_id: int) -> None:
    _LAST_WRITE_AT[(int(bot_id), int(group_id))] = time.monotonic()


async def _save_auto_episode(*, bot_id: int, group_id: int, content: str, source: str, cfg: LlmConfig) -> bool:
    try:
        ok = await save_memory_entry(bot_id, group_id, content, source=source, cfg=cfg)
    except Exception as exc:
        logger.warning("Auto episode save failed for bot [{}] and group [{}]: [{}]", bot_id, group_id, exc)
        return False
    if not ok:
        return False
    _mark_written(bot_id, group_id)
    try:
        from pallas.product.llm.memory.graph.extract import maybe_extract_after_episode_write

        await maybe_extract_after_episode_write(bot_id=bot_id, group_id=group_id, text=content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Auto episode extract hook failed for bot [{}] and group [{}]: [{}]", bot_id, group_id, exc)
    return True


async def maybe_auto_save_episode(
    *,
    bot_id: int,
    group_id: int | None,
    user_text: str,
    cfg: LlmConfig | None = None,
) -> bool:
    """若本轮用户话含明确事件信号，写入 memory（source=auto_episode）。"""
    c = cfg or get_llm_config()
    if not c.llm_memory_auto_episode_enabled:
        return False
    if not can_read_persistent_memory(c) or not is_llm_memory_store_available():
        return False
    if group_id is None:
        return False
    raw = (user_text or "").strip()
    if not raw or classify_memory_candidate(raw) != "episode_note":
        return False
    if not has_event_signal(raw):
        return False
    if not _cooldown_ok(int(bot_id), int(group_id), cooldown_sec=c.llm_memory_auto_episode_cooldown_sec):
        return False
    return await _save_auto_episode(
        bot_id=int(bot_id), group_id=int(group_id), content=raw, source="auto_episode", cfg=c
    )


def _group_episode_transcript(turns: list[Any]) -> str:
    user_turns = [turn for turn in turns if str(getattr(turn, "role", "")) == "user"]
    participants = {
        int(getattr(turn, "user_id", 0) or 0) for turn in user_turns if int(getattr(turn, "user_id", 0) or 0)
    }
    if len(user_turns) < 3 or len(participants) < 2:
        return ""
    lines: list[str] = []
    for turn in turns:
        if str(getattr(turn, "role", "")) != "user":
            continue
        text = str(getattr(turn, "content", "") or "").strip()
        if text:
            lines.append(f"群友：{text[:240]}")
    return "\n".join(lines)


async def maybe_auto_save_group_episode(*, bot_id: int, group_id: int | None, cfg: LlmConfig | None = None) -> bool:
    """从近期多人群聊中异步摘要共同事件，失败时不影响正常聊天。"""
    c = cfg or get_llm_config()
    if not c.llm_memory_auto_episode_enabled or not c.llm_memory_auto_episode_summary_enabled:
        return False
    if group_id is None or not can_read_persistent_memory(c) or not is_llm_memory_store_available():
        return False
    bid, gid = int(bot_id), int(group_id)
    if not _cooldown_ok(bid, gid, cooldown_sec=c.llm_memory_auto_episode_cooldown_sec):
        return False
    if not _daily_budget_ok(cfg=c):
        return False
    key = (bid, gid)
    if key in _GROUP_EPISODE_SUMMARY_IN_FLIGHT:
        return False
    _GROUP_EPISODE_SUMMARY_IN_FLIGHT.add(key)
    try:
        try:
            turns = await list_group_ambient_messages(bid, gid, limit=12, cfg=c)
        except Exception as exc:
            logger.warning("Group episode history read failed for bot [{}] and group [{}]: [{}]", bid, gid, exc)
            return False
        transcript = _group_episode_transcript(turns)
        if not transcript or _LAST_SUMMARY_SIGNATURE.get(key) == transcript:
            return False
        try:
            message = await complete_chat_message(
                [{"role": "system", "content": _GROUP_EPISODE_SYSTEM}, {"role": "user", "content": transcript}],
                model="",
                options={
                    "temperature": 0.2,
                    "max_tokens": task_token_budget("memory_extract"),
                },
                task="memory_extract",
                cfg=c,
            )
        except Exception as exc:
            logger.warning("Group episode summary failed for bot [{}] and group [{}]: [{}]", bid, gid, exc)
            return False
        summary = str(message.get("content") or "").strip() if isinstance(message, dict) else ""
        if summary in {"", "无", "无。"} or classify_memory_candidate(summary) != "episode_note":
            return False
        ok = await _save_auto_episode(bot_id=bid, group_id=gid, content=summary, source="auto_episode_summary", cfg=c)
        if ok:
            _LAST_SUMMARY_SIGNATURE[key] = transcript
            _bump_daily_budget(cfg=c)
        return ok
    finally:
        _GROUP_EPISODE_SUMMARY_IN_FLIGHT.discard(key)


def schedule_auto_save_group_episode(*, bot_id: int, group_id: int | None, cfg: LlmConfig | None = None) -> None:
    c = cfg or get_llm_config()
    if group_id is None or not c.llm_memory_auto_episode_summary_enabled:
        return
    try:
        asyncio.get_running_loop().create_task(
            maybe_auto_save_group_episode(bot_id=bot_id, group_id=group_id, cfg=c),
            name=f"group_episode_summary:{bot_id}:{group_id}",
        )
    except RuntimeError:
        return


def clear_auto_episode_cooldown_for_tests() -> None:
    global _DAILY_BUDGET_DATE, _DAILY_BUDGET_USED
    _LAST_WRITE_AT.clear()
    _LAST_SUMMARY_SIGNATURE.clear()
    _GROUP_EPISODE_SUMMARY_IN_FLIGHT.clear()
    _DAILY_BUDGET_DATE = ""
    _DAILY_BUDGET_USED = 0


def auto_episode_status_snapshot() -> dict[str, Any]:
    return {
        "tracked_groups": len(_LAST_WRITE_AT),
        "in_flight": len(_GROUP_EPISODE_SUMMARY_IN_FLIGHT),
        "daily_budget_used": _DAILY_BUDGET_USED,
    }
