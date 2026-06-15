"""本机可打开的 http 基址、NoneBot 日志环；独立模块，避免在 NoneBot 初始化前 import 插件包。"""

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

_LOG_ERROR_SINK_CB: Callable[[str, Mapping[str, Any]], None] | None = None


def set_log_error_capture(cb: Callable[[str, Mapping[str, Any]], None] | None) -> None:
    """由 pallas_webui 注册：在 NoneBot 日志 sink 中捕获 ERROR/CRITICAL 行并持久化。"""
    global _LOG_ERROR_SINK_CB
    _LOG_ERROR_SINK_CB = cb


_MAX = 20000
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
_shard_source_prefix_re = re.compile(r"^\[(?P<tag>[^\]]+)\] (?P<body>.+)$")
_stdlib_log_re = re.compile(
    r"^(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - (?P<lev>\w+) - (?P<msg>.*)$",
)
_nonebot_bracket_re = re.compile(
    r"^(?P<dt>\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(?P<lev>\w+)\] (?P<scope>[^|]+) \| (?P<msg>.*)$",
)
_exc_line_re = re.compile(
    r"^(?P<exc>[\w.]+(?:Error|Exception))(?:\s*:\s*(?P<msg>.*))?$",
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


def _strip_shard_log_prefix(raw: str) -> tuple[str, str]:
    """去掉分片合并前缀 ``[worker-N]``，返回 (source_tag, body)。"""
    tags: list[str] = []
    body = raw.strip()
    while True:
        m = _shard_source_prefix_re.match(body)
        if not m:
            break
        tags.append(m.group("tag"))
        body = m.group("body").strip()
    source_tag = tags[0] if len(tags) == 1 else "/".join(tags) if tags else ""
    return source_tag, body


def parse_nonebot_log_line(line: str, *, entry_id: int | None = None) -> dict[str, Any]:
    raw = line.rstrip("\n")
    source_tag, body = _strip_shard_log_prefix(raw)
    m = _log_line_re.match(body)
    if not m:
        m2 = _stdlib_log_re.match(body)
        if m2:
            lev_raw = (m2.group("lev") or "").strip().upper()
            scope = source_tag or "stdlib"
            iso = m2.group("dt")
            return {
                "id": entry_id if entry_id is not None else _next_stream_id(),
                "time": iso,
                "level": LEVEL_TO_BUCKET.get(lev_raw, "info"),
                "scope": scope,
                "message": m2.group("msg") or "",
            }
        m3 = _nonebot_bracket_re.match(body)
        if m3:
            lev_raw = (m3.group("lev") or "").strip().upper()
            scope = (m3.group("scope") or "").strip()[:120]
            if source_tag:
                scope = f"{source_tag}/{scope}" if scope else source_tag
            return {
                "id": entry_id if entry_id is not None else _next_stream_id(),
                "time": _mmdd_hms_to_iso(m3.group("dt")),
                "level": LEVEL_TO_BUCKET.get(lev_raw, "info"),
                "scope": scope,
                "message": m3.group("msg") or "",
            }
        m4 = _exc_line_re.match(body)
        if m4:
            msg = (m4.group("msg") or "").strip() or body
            scope = source_tag or "raw"
            return {
                "id": entry_id if entry_id is not None else _next_stream_id(),
                "time": "",
                "level": "error",
                "scope": scope,
                "message": msg,
            }
        if body.startswith(("Traceback", "  File ")):
            return {
                "id": entry_id if entry_id is not None else _next_stream_id(),
                "time": "",
                "level": "error",
                "scope": source_tag or "raw",
                "message": body[:2000],
            }
        return {
            "id": entry_id if entry_id is not None else _next_stream_id(),
            "time": "",
            "level": "info",
            "scope": source_tag or "raw",
            "message": body or raw,
        }
    dt_part = m.group("dt")
    lev_raw = (m.group("lev") or "").strip().upper()
    scope = (m.group("scope") or "").strip()[:120]
    if source_tag:
        scope = f"{source_tag}/{scope}" if scope else source_tag
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


def fill_missing_log_entry_times(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_time = ""
    for e in entries:
        t = str(e.get("time") or "").strip()
        if t:
            last_time = t
        elif last_time:
            e["time"] = last_time
    return entries


def merge_log_line_continuations(lines: list[str]) -> list[str]:
    """合并 traceback / pretty-print 等多行续行，避免结构化视图拆成多条 info。"""
    from src.platform.shard.logs.view import _is_log_continuation_body

    out: list[str] = []
    for line in lines:
        raw = line.rstrip("\n")
        if not raw.strip():
            continue
        _, body = _strip_shard_log_prefix(raw)
        if out and _is_log_continuation_body(body):
            out[-1] = f"{out[-1]}\n{raw}"
        else:
            out.append(raw)
    return out


def merge_log_entry_continuations(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from src.platform.shard.logs.view import _is_log_continuation_body

    out: list[dict[str, Any]] = []
    rank = {"debug": 0, "info": 1, "success": 2, "warn": 3, "error": 4}
    for e in entries:
        msg = str(e.get("message") or "")
        if out and _is_log_continuation_body(msg):
            prev = out[-1]
            prev_msg = str(prev.get("message") or "")
            prev["message"] = f"{prev_msg}\n{msg}" if prev_msg else msg
            pl = str(prev.get("level") or "info")
            cl = str(e.get("level") or "info")
            if rank.get(cl, 1) > rank.get(pl, 1):
                prev["level"] = cl
            continue
        out.append(dict(e))
    return out


def tail_nonebot_log_entries_scoped(
    n: int,
    scope: LogScope,
    *,
    source: str | None = None,
) -> list[dict[str, Any]]:
    lines = merge_log_line_continuations(tail_nonebot_log_lines_scoped(n, scope, source=source))
    out: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        out.append(parse_nonebot_log_line(line, entry_id=-(i + 1)))
    return fill_missing_log_entry_times(out)


def subscribe_nonebot_log_stream(max_queue: int = 400) -> tuple[queue.Queue[dict[str, Any]], Callable[[], None]]:
    """订阅实时日志；队列元素含 entry 与 scopes。"""
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


def _entry_matches_log_source(entry: dict[str, Any], source: str | None) -> bool:
    want = (source or "all").strip() or "all"
    if want == "all":
        return True
    scope = str(entry.get("scope") or "")
    if want == "hub":
        return scope.startswith("hub/") or scope in ("hub", "hub-file")
    return scope == want or scope.startswith(f"{want}/")


async def iter_nonebot_log_sse(
    scope: LogScope,
    *,
    source: str | None = None,
) -> AsyncIterator[str]:
    """SSE：首包 ``ready``，随后 JSON 条目"""
    q, unsub = subscribe_nonebot_log_stream()
    shard_tailer = None
    try:
        from src.platform.bot_runtime.roles import is_sharded_hub

        if is_sharded_hub():
            from src.platform.shard.logs.view import ShardLogTailer

            shard_tailer = ShardLogTailer(source=source)
    except Exception:
        shard_tailer = None

    try:
        yield f"data: {json.dumps({'type': 'ready'}, ensure_ascii=False)}\n\n"
        while True:

            def _pull() -> dict[str, Any] | None:
                try:
                    return q.get(timeout=2.0)
                except queue.Empty:
                    return None

            payload = await asyncio.to_thread(_pull)
            hub_sent = False
            if payload is not None:
                scopes = payload.get("scopes") or {}
                if scope != "webui" or scopes.get("webui"):
                    if scope != "protocol" or scopes.get("protocol"):
                        entry = payload.get("entry")
                        if isinstance(entry, dict) and _entry_matches_log_source(entry, source):
                            filled = fill_missing_log_entry_times([dict(entry)])
                            yield f"data: {json.dumps(filled[0], ensure_ascii=False)}\n\n"
                            hub_sent = True

            shard_sent = False
            new_lines: list[str] = []
            if shard_tailer is not None:

                def _poll_shard() -> list[str]:
                    return shard_tailer.poll_new_lines(scope=scope)

                new_lines = await asyncio.to_thread(_poll_shard)
                last_time = ""
                for line in new_lines:
                    e = parse_nonebot_log_line(line)
                    if not _entry_matches_log_source(e, source):
                        continue
                    t = str(e.get("time") or "").strip()
                    if t:
                        last_time = t
                    elif last_time:
                        e["time"] = last_time
                    yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                    shard_sent = True

            if not hub_sent and not shard_sent:
                yield ": heartbeat\n\n"
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
    """是否与控制台或协议端相关。"""
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
    if record is not None and _LOG_ERROR_SINK_CB is not None:
        try:
            lvl = record["level"]
            lev_name = str(lvl.name).upper() if hasattr(lvl, "name") else str(lvl).upper()
            if lev_name in ("ERROR", "CRITICAL"):
                _LOG_ERROR_SINK_CB(text, record)
        except Exception:
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
        # 分片多进程同时刷启动日志时，enqueue 可能阻塞 lifespan 导致 worker 永不 listen
        enqueue=False,
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


def tail_nonebot_log_lines_scoped(
    n: int,
    scope: LogScope,
    *,
    source: str | None = None,
) -> list[str]:
    want = (source or "all").strip() or "all"
    if scope == "webui":
        base = tail_nonebot_log_lines_webui(n)
    elif scope == "protocol":
        base = tail_nonebot_log_lines_protocol(n)
    else:
        base = tail_nonebot_log_lines(n)
    try:
        from src.platform.bot_runtime.roles import is_sharded_hub

        if is_sharded_hub():
            from src.platform.shard.logs.view import merge_cluster_log_lines

            return merge_cluster_log_lines(n, scope, hub_ring_lines=base, source=source)
    except Exception:
        pass
    if want == "all":
        return base
    from src.platform.shard.logs.view import collect_shard_file_log_lines, prefix_log_source

    if want == "hub":
        return [prefix_log_source(line, "hub") for line in base]
    return collect_shard_file_log_lines(per_file=n, scope=scope, source=source)[-n:]
