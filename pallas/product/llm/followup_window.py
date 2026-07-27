"""续聊软窗口：硬触发（@ / 别名提及）后，同一用户短时间内可免唤醒接话。

规则：
- 按 bot_id 隔离，避免同进程多牛串号
- 窗口从最近一次硬触发起算；软触发不刷新硬触发时刻（续聊不续费）
- 另有整轮天花板，避免连续硬触发无限续命
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock

_GC_THRESHOLD = 512
_lock = Lock()


@dataclass
class _BurstState:
    burst_start: float
    last_hard_ts: float


_states: dict[str, _BurstState] = {}


def clear_followup_window_state() -> None:
    with _lock:
        _states.clear()


def _key(bot_id: int, group_id: int, user_id: int) -> str:
    return f"{int(bot_id)}::{int(group_id)}::{int(user_id)}"


def _maybe_gc(window_seconds: int) -> None:
    if len(_states) < _GC_THRESHOLD:
        return
    now = time.time()
    dead = [k for k, st in _states.items() if (now - st.last_hard_ts) > float(window_seconds)]
    for k in dead:
        del _states[k]


def note_hard_speak_trigger(
    bot_id: int | None,
    group_id: int | None,
    user_id: int | None,
    *,
    window_seconds: int,
    max_total_seconds: int,
    now: float | None = None,
) -> None:
    if bot_id is None or group_id is None or user_id is None:
        return
    if int(window_seconds) <= 0:
        return
    ts = time.time() if now is None else float(now)
    k = _key(int(bot_id), int(group_id), int(user_id))
    with _lock:
        st = _states.get(k)
        if st is None or (ts - st.last_hard_ts) > float(window_seconds):
            _states[k] = _BurstState(burst_start=ts, last_hard_ts=ts)
        else:
            st.last_hard_ts = ts
        _maybe_gc(int(window_seconds))


def in_followup_window(
    bot_id: int | None,
    group_id: int | None,
    user_id: int | None,
    *,
    window_seconds: int,
    max_total_seconds: int,
    now: float | None = None,
) -> bool:
    if bot_id is None or group_id is None or user_id is None:
        return False
    if int(window_seconds) <= 0:
        return False
    k = _key(int(bot_id), int(group_id), int(user_id))
    with _lock:
        st = _states.get(k)
    if st is None:
        return False
    ts = time.time() if now is None else float(now)
    if (ts - st.burst_start) > float(max_total_seconds):
        return False
    return (ts - st.last_hard_ts) <= float(window_seconds)
