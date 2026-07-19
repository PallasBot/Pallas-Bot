"""启发式自动写入群 episode 记忆（不跑大模型摘要）。"""

from __future__ import annotations

import time
from typing import Any

from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.kernel.memory_governance import can_read_persistent_memory
from pallas.product.llm.memory.policy import classify_memory_candidate
from pallas.product.llm.memory.store import is_llm_memory_store_available, save_memory_entry

_LAST_WRITE_AT: dict[tuple[int, int], float] = {}


def _cooldown_ok(bot_id: int, group_id: int, *, cooldown_sec: int) -> bool:
    if cooldown_sec <= 0:
        return True
    key = (int(bot_id), int(group_id))
    last = _LAST_WRITE_AT.get(key, 0.0)
    return (time.monotonic() - last) >= float(cooldown_sec)


def _mark_written(bot_id: int, group_id: int) -> None:
    _LAST_WRITE_AT[(int(bot_id), int(group_id))] = time.monotonic()


async def maybe_auto_save_episode(
    *,
    bot_id: int,
    group_id: int | None,
    user_text: str,
    cfg: LlmConfig | None = None,
) -> bool:
    """若本轮用户话像有群价值的旧事，写入 memory（source=auto_episode）。"""
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
    if not _cooldown_ok(int(bot_id), int(group_id), cooldown_sec=c.llm_memory_auto_episode_cooldown_sec):
        return False
    try:
        ok = await save_memory_entry(
            int(bot_id),
            int(group_id),
            raw,
            source="auto_episode",
            cfg=c,
        )
    except Exception as exc:
        logger.warning("auto_episode save failed bot={} group={} err={}", bot_id, group_id, exc)
        return False
    if ok:
        _mark_written(int(bot_id), int(group_id))
    return bool(ok)


def clear_auto_episode_cooldown_for_tests() -> None:
    _LAST_WRITE_AT.clear()


def auto_episode_status_snapshot() -> dict[str, Any]:
    return {"tracked_groups": len(_LAST_WRITE_AT)}
