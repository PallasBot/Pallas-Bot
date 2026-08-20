"""按群随机静默：听到「闭嘴」后一段时间内压制该群主动发言。

状态保存在进程内存中，重启即清空；解除靠自动到期或说「说话」。
"""

from __future__ import annotations

import random
import threading
import time

_SILENCES: dict[tuple[int, int], float] = {}
_SILENCES_LOCK = threading.Lock()

DEFAULT_MIN_SEC = 30
DEFAULT_MAX_SEC = 300


def clear_all_silences() -> None:
    """清空全部静默状态（测试用）。"""
    with _SILENCES_LOCK:
        _SILENCES.clear()


def trigger_silence(
    bot_id: int,
    group_id: int,
    *,
    min_sec: int = DEFAULT_MIN_SEC,
    max_sec: int = DEFAULT_MAX_SEC,
) -> int:
    """对该群触发随机时长静默，返回静默秒数。"""
    if min_sec > max_sec:
        min_sec, max_sec = max_sec, min_sec
    seconds = random.randint(int(min_sec), int(max_sec))
    with _SILENCES_LOCK:
        _SILENCES[(int(bot_id), int(group_id))] = time.monotonic() + seconds
    return seconds


def silence_remaining_sec(bot_id: int, group_id: int) -> float:
    with _SILENCES_LOCK:
        until = _SILENCES.get((int(bot_id), int(group_id)))
    if until is None:
        return 0.0
    return max(0.0, until - time.monotonic())


def is_group_silenced(bot_id: int, group_id: int) -> bool:
    return silence_remaining_sec(bot_id, group_id) > 0


def try_clear_silence(bot_id: int, group_id: int) -> bool:
    """清除某群静默状态（测试/运维用）。"""
    with _SILENCES_LOCK:
        return _SILENCES.pop((int(bot_id), int(group_id)), None) is not None
