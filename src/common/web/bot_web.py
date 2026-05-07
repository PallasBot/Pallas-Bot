"""本机可打开的 http 基址、NoneBot 日志环（管理页用）；独立模块，避免在 NoneBot 初始化前 import 插件包。"""

from __future__ import annotations

import asyncio
import json
import queue
import re
import threading
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

LogScope = Literal["all", "webui", "protocol"]

_MAX = 2000
_lines: deque[str] = deque(maxlen=_MAX)
_lines_webui: deque[str] = deque(maxlen=_MAX)
_lines_protocol: deque[str] = deque(maxlen=_MAX)
_lock = threading.Lock()
_installed: bool = False

_stream_id_lock = threading.Lock()
_stream_seq = 0

_log_line_re = re.compile(
    r"^(?P<dt>\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (?P<lev>\S+)\s* \| (?P<scope>[^:]+):(?P<lineno>\d+) - (?P<msg>.*)$",
)

_subscribers: list[queue.Queue[dict[str, Any]]] = []
_sub_lock = threading.Lock()

LEVEL_TO_BUCKET: dict[str, str] = {
    "TRACE": "debug",
    "DEBUG": "debug",
    "INFO": "info",
    "SUCCESS": "success",
    "WARNING": "warn",
    "ERROR": "error",
    "CRITICAL": "error",
}


def _next_stream_id() -> int:
    global _stream_seq
    with _stream_id_lock:
        _stream_seq += 1
        return _stream_seq


def parse_nonebot_log_line(line: str, *, entry_id: int | None = None) -> dict[str, Any]:
    raw = line.rstrip("\n")
    m = _log_line_re.match(raw.strip())
    if not m:
        return {
            "id": entry_id if entry_id is not None else _next_stream_id(),
            "time": datetime.now().isoformat(timespec="seconds"),
            "level": "info",
            "scope": "raw",
            "message": raw,
        }
    dt_part = m.group("dt")
    lev_raw = (m.group("lev") or "").strip().upper()
    scope = (m.group("scope") or "").strip()[:120]
    msg = m.group("msg") or ""
    level = LEVEL_TO_BUCKET.get(lev_raw, "info")
    iso_time = _mmdd_hms_to_iso(dt_part)
    return {
        "id": entry_id if entry_id is not None else _next_stream_id(),
        "time": iso_time,
        "level": level,
        "scope": scope,
        "message": msg,
    }


def _mmdd_hms_to_iso(mmdd_hms: str) -> str:
    """``MM-DD HH:mm:ss`` → 当前年份下的 ISO 本地时间字符串。"""
    try:
        mo, rest = mmdd_hms.split("-", 1)
        day, hm = rest.split(" ", 1)
        h, mi, s = hm.split(":")
        now = datetime.now()
        dt = datetime(now.year, int(mo), int(day), int(h), int(mi), int(s))
        return dt.isoformat(timespec="seconds")
    except (ValueError, TypeError):
        return datetime.now().isoformat(timespec="seconds")


def tail_nonebot_log_entries_scoped(n: int, scope: LogScope) -> list[dict[str, Any]]:
    lines = tail_nonebot_log_lines_scoped(n, scope)
    out: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        e = parse_nonebot_log_line(line, entry_id=-(i + 1))
        out.append(e)
    return out


def subscribe_nonebot_log_stream(max_queue: int = 400) -> tuple[queue.Queue[dict[str, Any]], Callable[[], None]]:
    """订阅实时日志；队列元素含 entry 与 scopes（all/webui/protocol）。"""
    q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_queue)
    with _sub_lock:
        _subscribers.append(q)

    def unsub() -> None:
        with _sub_lock:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass

    return q, unsub


async def iter_nonebot_log_sse(scope: LogScope) -> AsyncIterator[str]:
    """SSE：首包 ``ready``，随后 JSON 条目；心跳保持连接。"""
    q, unsub = subscribe_nonebot_log_stream()
    try:
        yield f"data: {json.dumps({'type': 'ready'}, ensure_ascii=False)}\n\n"
        while True:

            def _pull() -> dict[str, Any] | None:
                try:
                    return q.get(timeout=22.0)
                except queue.Empty:
                    return None

            payload = await asyncio.to_thread(_pull)
            if payload is None:
                yield ": heartbeat\n\n"
                continue
            scopes = payload.get("scopes") or {}
            if scope == "webui" and not scopes.get("webui"):
                continue
            if scope == "protocol" and not scopes.get("protocol"):
                continue
            entry = payload.get("entry")
            if isinstance(entry, dict):
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
    finally:
        unsub()


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
    entry = parse_nonebot_log_line(text)
    in_webui = bool(record is not None and nonebot_log_record_matches_http_facet(record, "webui"))
    in_protocol = bool(record is not None and nonebot_log_record_matches_http_facet(record, "protocol"))
    payload = {
        "entry": entry,
        "scopes": {"all": True, "webui": in_webui, "protocol": in_protocol},
    }
    with _lock:
        _lines.append(text)
        if record is not None:
            if in_webui:
                _lines_webui.append(text)
            if in_protocol:
                _lines_protocol.append(text)
    if _subscribers:
        with _sub_lock:
            subs = list(_subscribers)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass


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
