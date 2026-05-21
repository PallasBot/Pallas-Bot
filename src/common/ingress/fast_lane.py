"""Fast lane：私聊、牛牛命令、决斗/八角笼等优先；慢路径仅约束通过分片的水群。"""

from __future__ import annotations

import asyncio

from nonebot.adapters.onebot.v11 import (
    FriendRequestEvent,
    GroupMessageEvent,
    GroupRequestEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from src.common.ingress.config import get_ingress_config

_SLOW_EVENT_SEM: asyncio.Semaphore | None = None
_SLOW_SEM_LIMIT: int | None = None
_SLOW_OVERFLOW_SEM: asyncio.Semaphore | None = None
_SLOW_OVERFLOW_LIMIT: int | None = None
_SLOW_SLOT_HELD: set[int] = set()
_SLOW_OVERFLOW_HELD: set[int] = set()


def _slow_sem() -> asyncio.Semaphore:
    global _SLOW_EVENT_SEM, _SLOW_SEM_LIMIT
    limit = get_ingress_config().ingress_slow_concurrency
    if _SLOW_EVENT_SEM is None or _SLOW_SEM_LIMIT != limit:
        _SLOW_EVENT_SEM = asyncio.Semaphore(limit)
        _SLOW_SEM_LIMIT = limit
    return _SLOW_EVENT_SEM


def _slow_overflow_sem() -> asyncio.Semaphore | None:
    global _SLOW_OVERFLOW_SEM, _SLOW_OVERFLOW_LIMIT
    limit = get_ingress_config().ingress_slow_overflow_concurrency
    if limit <= 0:
        return None
    if _SLOW_OVERFLOW_SEM is None or _SLOW_OVERFLOW_LIMIT != limit:
        _SLOW_OVERFLOW_SEM = asyncio.Semaphore(limit)
        _SLOW_OVERFLOW_LIMIT = limit
    return _SLOW_OVERFLOW_SEM


def clear_ingress_slow_path_runtime_state() -> None:
    """失效慢路径信号量与占槽记录；保存通用配置后由 dispatch 热重载调用。"""
    global _SLOW_EVENT_SEM, _SLOW_SEM_LIMIT, _SLOW_OVERFLOW_SEM, _SLOW_OVERFLOW_LIMIT
    _SLOW_EVENT_SEM = None
    _SLOW_SEM_LIMIT = None
    _SLOW_OVERFLOW_SEM = None
    _SLOW_OVERFLOW_LIMIT = None
    _SLOW_SLOT_HELD.clear()
    _SLOW_OVERFLOW_HELD.clear()


def ingress_fast_lane_enabled() -> bool:
    return get_ingress_config().ingress_fast_lane_enabled


def is_duel_ingress_priority_plaintext(plain: str) -> bool:
    from src.plugins.duel.duel_bots import is_cage_plaintext

    text = plain.strip()
    if is_cage_plaintext(text):
        return True
    if text.startswith("牛牛决斗"):
        return True
    return text == "决斗事件重载"


def is_command_like_plaintext(plain: str, *, is_tome: bool = False) -> bool:
    text = plain.strip()
    if is_duel_ingress_priority_plaintext(text):
        return True
    prefix = get_ingress_config().fast_lane_command_prefix
    if prefix and text.startswith(prefix):
        return True
    return is_tome


def should_repeater_skip_group_message(event: GroupMessageEvent) -> bool:
    """牛牛命令/@ 牛 不走复读学习，保留 greeting 全员同响「牛牛」「帕拉斯」接话。"""
    plain = event.get_plaintext().strip()
    if plain in get_ingress_config().greeting_fanout_set:
        return False
    try:
        to_me = event.is_tome()
    except Exception:
        to_me = False
    return is_command_like_plaintext(plain, is_tome=to_me)


def is_fast_lane_event(event: MessageEvent | FriendRequestEvent | GroupRequestEvent) -> bool:
    if isinstance(event, (PrivateMessageEvent, FriendRequestEvent, GroupRequestEvent)):
        return True
    if isinstance(event, GroupMessageEvent):
        try:
            to_me = event.is_tome()
        except Exception:
            to_me = False
        return is_command_like_plaintext(event.get_plaintext(), is_tome=to_me)
    return False


def should_apply_ingress_slow_path(event: object) -> bool:
    """慢路径仅作用于：通过分片后、非 fast lane、非 greeting 全员同响的群消息。"""
    if not ingress_fast_lane_enabled():
        return False
    if type(event).__name__.endswith("MetaEvent"):
        return False
    if not isinstance(event, GroupMessageEvent):
        return False
    if is_fast_lane_event(event):
        return False
    from src.common.ingress.gate import ingress_group_message_fanout_all_bots

    if ingress_group_message_fanout_all_bots(event):
        return False
    return True


def slow_event_slot_held(event: object) -> bool:
    return id(event) in _SLOW_SLOT_HELD


def slow_event_overflow_held(event: object) -> bool:
    return id(event) in _SLOW_OVERFLOW_HELD


async def acquire_slow_event_slot(event: object) -> bool:
    if not should_apply_ingress_slow_path(event):
        return True
    eid = id(event)
    if eid in _SLOW_SLOT_HELD or eid in _SLOW_OVERFLOW_HELD:
        return True
    try:
        await asyncio.wait_for(
            _slow_sem().acquire(),
            timeout=get_ingress_config().ingress_slow_acquire_sec,
        )
    except TimeoutError:
        cfg = get_ingress_config()
        if cfg.ingress_slow_drop_on_timeout:
            return False
        overflow = _slow_overflow_sem()
        if overflow is None:
            return True
        try:
            await asyncio.wait_for(overflow.acquire(), timeout=0.05)
        except TimeoutError:
            return False
        _SLOW_OVERFLOW_HELD.add(eid)
        return True
    _SLOW_SLOT_HELD.add(eid)
    return True


def release_slow_event_slot(event: object) -> None:
    if not should_apply_ingress_slow_path(event):
        return
    eid = id(event)
    if eid in _SLOW_SLOT_HELD:
        _SLOW_SLOT_HELD.discard(eid)
        try:
            _slow_sem().release()
        except ValueError:
            pass
        return
    if eid in _SLOW_OVERFLOW_HELD:
        _SLOW_OVERFLOW_HELD.discard(eid)
        overflow = _slow_overflow_sem()
        if overflow is not None:
            try:
                overflow.release()
            except ValueError:
                pass
