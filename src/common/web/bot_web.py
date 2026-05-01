"""本机可打开的 http 基址、NoneBot 日志环（管理页用）；独立模块，避免在 NoneBot 初始化前 import 插件包。"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

_MAX = 2000
_lines: deque[str] = deque(maxlen=_MAX)
_lines_webui: deque[str] = deque(maxlen=_MAX)
_lines_protocol: deque[str] = deque(maxlen=_MAX)
_lock = threading.Lock()
_installed: bool = False

LogScope = Literal["all", "webui", "protocol"]


def public_base_url(*, host: str | object | None, port: int | object | None) -> str:
    h = (str(host).strip() if host is not None else "") or "127.0.0.1"
    if h in ("0.0.0.0", "::", "[::]"):
        h = "127.0.0.1"
    try:
        p = int(port) if port is not None else 8080
    except (TypeError, ValueError):
        p = 8080
    return f"http://{h}:{p}"


def nonebot_log_record_matches_http_facet(
    record: Mapping[str, Any],
    facet: Literal["webui", "protocol"],
) -> bool:
    """是否与控制台或协议端相关（独立日志环；匹配插件 id 或正文中的 realm 标记）。"""
    name = str(record.get("name") or "")
    raw_msg = record.get("message")
    mstr = raw_msg if isinstance(raw_msg, str) else ""
    if facet == "webui":
        return name == "pallas_webui" or "[pallas-webui]" in mstr
    return name == "pallas_protocol" or "[pallas-protocol]" in mstr


def _sink_dispatch(message: object) -> None:
    text = str(message).rstrip("\n")
    if not text:
        return
    record = getattr(message, "record", None)
    with _lock:
        _lines.append(text)
        if record is not None:
            if nonebot_log_record_matches_http_facet(record, "webui"):
                _lines_webui.append(text)
            if nonebot_log_record_matches_http_facet(record, "protocol"):
                _lines_protocol.append(text)


def install_nonebot_log_sink() -> None:
    global _installed
    if _installed:
        return
    from nonebot.log import logger

    logger.add(
        _sink_dispatch,
        level="INFO",
        format="{time:MM-DD HH:mm:ss} | {level:<8} | {name}:{line} - {message}",
        colorize=False,
        enqueue=True,
    )
    _installed = True


def tail_nonebot_log_lines(n: int) -> list[str]:
    if n <= 0:
        return []
    with _lock:
        return list(_lines)[-n:]


def tail_nonebot_log_lines_webui(n: int) -> list[str]:
    if n <= 0:
        return []
    with _lock:
        return list(_lines_webui)[-n:]


def tail_nonebot_log_lines_protocol(n: int) -> list[str]:
    if n <= 0:
        return []
    with _lock:
        return list(_lines_protocol)[-n:]


def tail_nonebot_log_lines_scoped(n: int, scope: LogScope) -> list[str]:
    if scope == "webui":
        return tail_nonebot_log_lines_webui(n)
    if scope == "protocol":
        return tail_nonebot_log_lines_protocol(n)
    return tail_nonebot_log_lines(n)
