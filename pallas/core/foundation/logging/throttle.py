"""限频日志：高频路径（每消息/每请求）只周期输出一次，避免故障刷屏。"""

from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.Lock()
_LAST_EMIT_AT: dict[str, float] = {}


def log_rate_limited(
    logger: Any,
    level: str,
    key: str,
    msg: str,
    *args: Any,
    interval_sec: float = 30.0,
) -> bool:
    """同一 key 在 interval_sec 内只输出一次；返回本次是否输出。

    key 用模块+动作等粗粒度身份，细节放 msg 参数；level 支持 loguru 级别名
    （warning / info / error / exception）。
    """
    now = time.monotonic()
    with _LOCK:
        last = _LAST_EMIT_AT.get(key)
        if last is not None and now - last < interval_sec:
            return False
        _LAST_EMIT_AT[key] = now
    getattr(logger, level)(msg, *args)
    return True
