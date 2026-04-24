"""本机可打开的 http 基址、NoneBot 日志环（管理页用）；独立模块，避免在 NoneBot 初始化前 import 插件包。"""

from __future__ import annotations

import threading
from collections import deque

_MAX = 2000
_lines: deque[str] = deque(maxlen=_MAX)
_lock = threading.Lock()
_installed: bool = False


def public_base_url(*, host: str | object | None, port: int | object | None) -> str:
    h = (str(host).strip() if host is not None else "") or "127.0.0.1"
    if h in ("0.0.0.0", "::", "[::]"):
        h = "127.0.0.1"
    try:
        p = int(port) if port is not None else 8080
    except (TypeError, ValueError):
        p = 8080
    return f"http://{h}:{p}"


def install_nonebot_log_sink() -> None:
    global _installed
    if _installed:
        return
    from nonebot.log import logger

    def sink(msg: object) -> None:
        s = str(msg).rstrip("\n")
        if s:
            with _lock:
                _lines.append(s)

    logger.add(
        sink,
        level="INFO",
        format="{time:MM-DD HH:mm:ss} | {level} | {name}:{line} - {message}",
        colorize=False,
        enqueue=True,
    )
    _installed = True


def tail_nonebot_log_lines(n: int) -> list[str]:
    if n <= 0:
        return []
    with _lock:
        return list(_lines)[-n:]
