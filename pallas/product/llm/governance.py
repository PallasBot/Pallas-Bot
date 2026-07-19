"""LLM 治理：群级开关、冷却、并发槽与 PG 池背压。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.db.pool_budget import cap_by_pg_pool, pg_pool_under_pressure

from .config import LlmConfig, get_llm_config

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
else:
    MessageEvent = object  # noqa: N806

LLM_CHAT_COMMAND_ID = "llm_chat.chat"

_chat_sem: asyncio.Semaphore | None = None
_chat_sem_limit: int | None = None
_skipped_busy: int = 0
_skipped_pressure: int = 0


def clear_llm_chat_governance_state() -> None:
    global _chat_sem, _chat_sem_limit
    _chat_sem = None
    _chat_sem_limit = None


def parse_group_id_set(raw: str | None) -> set[int]:
    if not raw or not raw.strip():
        return set()
    text = raw.strip()
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return set()
        if not isinstance(data, list):
            return set()
        out: set[int] = set()
        for item in data:
            try:
                out.add(int(item))
            except (TypeError, ValueError):
                continue
        return out
    out = set()
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def llm_chat_disabled_group_ids(cfg: LlmConfig | None = None) -> set[int]:
    c = cfg or get_llm_config()
    if c.llm_chat_disabled_group_ids:
        return set(c.llm_chat_disabled_group_ids)
    raw = repo_env_raw_value("LLM_CHAT_DISABLED_GROUP_IDS")
    return parse_group_id_set(raw)


def llm_chat_concurrency_limit(cfg: LlmConfig | None = None) -> int:
    c = cfg or get_llm_config()
    requested = max(1, int(c.llm_chat_max_concurrency))
    return cap_by_pg_pool(requested, workload_fraction=0.20)


def llm_chat_sem() -> asyncio.Semaphore:
    global _chat_sem, _chat_sem_limit
    limit = llm_chat_concurrency_limit()
    if _chat_sem is None or _chat_sem_limit != limit:
        _chat_sem = asyncio.Semaphore(limit)
        _chat_sem_limit = limit
    return _chat_sem


def is_llm_chat_group_allowed(group_id: int | None, *, cfg: LlmConfig | None = None) -> bool:
    if group_id is None:
        return True
    disabled = llm_chat_disabled_group_ids(cfg)
    return int(group_id) not in disabled


def should_skip_llm_chat_under_pressure(*, hot_path: bool = True) -> bool:
    global _skipped_pressure
    threshold = 0.70 if hot_path else 0.55
    if pg_pool_under_pressure(threshold=threshold):
        _skipped_pressure += 1
        return True
    return False


class LlmChatSlot:
    __slots__ = ("acquired",)

    def __init__(self) -> None:
        self.acquired = False


async def try_acquire_llm_chat_slot(*, wait: bool = False, cfg: LlmConfig | None = None) -> LlmChatSlot | None:
    global _skipped_busy
    c = cfg or get_llm_config()
    if not c.llm_governance_enabled:
        slot = LlmChatSlot()
        slot.acquired = True
        return slot
    if should_skip_llm_chat_under_pressure(hot_path=True):
        return None
    sem = llm_chat_sem()
    if wait:
        await sem.acquire()
        slot = LlmChatSlot()
        slot.acquired = True
        return slot
    if sem.locked():
        _skipped_busy += 1
        return None
    await sem.acquire()
    slot = LlmChatSlot()
    slot.acquired = True
    return slot


def release_llm_chat_slot(slot: LlmChatSlot | None) -> None:
    if slot is None or not slot.acquired:
        return
    c = get_llm_config()
    if not c.llm_governance_enabled:
        slot.acquired = False
        return
    llm_chat_sem().release()
    slot.acquired = False


class LlmChatGovernance:
    def __init__(self, *, wait: bool = False, cfg: LlmConfig | None = None) -> None:
        self._wait = wait
        self._cfg = cfg
        self._slot: LlmChatSlot | None = None
        self.skipped = False

    async def __aenter__(self) -> LlmChatGovernance:
        self._slot = await try_acquire_llm_chat_slot(wait=self._wait, cfg=self._cfg)
        if self._slot is None:
            self.skipped = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        release_llm_chat_slot(self._slot)
        self._slot = None


async def is_llm_chat_cooldown_ready(event: MessageEvent, *, default_cd_sec: int | None = None) -> bool:
    from pallas.core.limits import get_command_cooldown_sec, is_command_cooldown_ready

    cd_sec = get_command_cooldown_sec(LLM_CHAT_COMMAND_ID, default_cd_sec)
    if cd_sec is None or cd_sec <= 0:
        return True
    return await is_command_cooldown_ready(event, LLM_CHAT_COMMAND_ID, default_cd_sec=default_cd_sec)


async def refresh_llm_chat_cooldown(event: MessageEvent, *, default_cd_sec: int | None = None) -> None:
    from pallas.core.limits import get_command_cooldown_sec, refresh_command_cooldown

    cd_sec = get_command_cooldown_sec(LLM_CHAT_COMMAND_ID, default_cd_sec)
    if cd_sec is None or cd_sec <= 0:
        return
    await refresh_command_cooldown(event, LLM_CHAT_COMMAND_ID, default_cd_sec=default_cd_sec)


async def check_llm_chat_gate(
    event: object,
    group_id: int | None,
    *,
    cfg: LlmConfig | None = None,
) -> str | None:
    c = cfg or get_llm_config()
    if not c.llm_governance_enabled:
        return None
    if not is_llm_chat_group_allowed(group_id, cfg=c):
        return "group_disabled"
    from nonebot.adapters.onebot.v11 import MessageEvent as ObMessageEvent

    if isinstance(event, ObMessageEvent) and not await is_llm_chat_cooldown_ready(
        event,
        default_cd_sec=c.llm_chat_cooldown_sec,
    ):
        return "cooldown"
    if should_skip_llm_chat_under_pressure(hot_path=True):
        if _skipped_pressure == 1 or _skipped_pressure % 50 == 0:
            logger.debug("llm chat skipped under pg pool pressure (count={})", _skipped_pressure)
        return "pool_pressure"
    return None
