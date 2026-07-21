"""控制台 HTTP 基址与日志环。"""

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
_entry_ring: deque[dict[str, Any]] = deque(maxlen=4000)
_lock = threading.Lock()
_entries_lock = threading.Lock()
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
    """去掉日志里的 worker 前缀，返回来源标签与正文。

    保留正文行首缩进（如 ``  File ``），避免 traceback 续行被误判为普通 info。
    """
    tags: list[str] = []
    body = raw.rstrip("\n")
    while True:
        m = _shard_source_prefix_re.match(body)
        if not m:
            break
        tags.append(m.group("tag"))
        body = m.group("body")
    source_tag = tags[0] if len(tags) == 1 else "/".join(tags) if tags else ""
    return source_tag, body


def _is_traceback_body(body: str) -> bool:
    s = body.lstrip()
    if s.startswith("Traceback"):
        return True
    if body.startswith("  File ") or s.startswith('File "'):
        return True
    if s.startswith("During handling of the above exception"):
        return True
    if re.match(r"^raise\s+[\w.]*(?:Error|Exception)\b", s):
        return True
    if _exc_line_re.match(s):
        return True
    return False


def _with_multiline_msg(msg: str, remainder: str) -> str:
    if not remainder:
        return msg
    return f"{msg}\n{remainder}" if msg else remainder


def parse_nonebot_log_line(line: str, *, entry_id: int | None = None) -> dict[str, Any]:
    raw = line.rstrip("\n")
    source_tag, body = _strip_shard_log_prefix(raw)
    # loguru/sink 常把整段 traceback 放进同一条；只对首行做格式匹配
    first, sep, remainder = body.partition("\n")
    head = first if sep else body

    m = _log_line_re.match(head)
    if not m:
        m2 = _stdlib_log_re.match(head)
        if m2:
            lev_raw = (m2.group("lev") or "").strip().upper()
            scope = source_tag or "stdlib"
            iso = m2.group("dt")
            msg = _with_multiline_msg(m2.group("msg") or "", remainder)
            return {
                "id": entry_id if entry_id is not None else _next_stream_id(),
                "time": iso,
                "level": LEVEL_TO_BUCKET.get(lev_raw, "info"),
                "scope": scope,
                "message": msg,
            }
        m3 = _nonebot_bracket_re.match(head)
        if m3:
            lev_raw = (m3.group("lev") or "").strip().upper()
            scope = (m3.group("scope") or "").strip()[:120]
            if source_tag:
                scope = f"{source_tag}/{scope}" if scope else source_tag
            msg = _with_multiline_msg(m3.group("msg") or "", remainder)
            return {
                "id": entry_id if entry_id is not None else _next_stream_id(),
                "time": _mmdd_hms_to_iso(m3.group("dt")),
                "level": LEVEL_TO_BUCKET.get(lev_raw, "info"),
                "scope": scope,
                "message": msg,
            }
        head_l = head.lstrip()
        m4 = _exc_line_re.match(head_l)
        if m4:
            msg = _with_multiline_msg((m4.group("msg") or "").strip() or head_l, remainder)
            scope = source_tag or "raw"
            return {
                "id": entry_id if entry_id is not None else _next_stream_id(),
                "time": "",
                "level": "error",
                "scope": scope,
                "message": msg[:2000],
            }
        if _is_traceback_body(head):
            return {
                "id": entry_id if entry_id is not None else _next_stream_id(),
                "time": "",
                "level": "error",
                "scope": source_tag or "raw",
                "message": (body if remainder else head)[:2000],
            }
        return {
            "id": entry_id if entry_id is not None else _next_stream_id(),
            "time": "",
            "level": "info",
            "scope": source_tag or "raw",
            "message": (body or raw)[:2000],
        }
    dt_part = m.group("dt")
    lev_raw = (m.group("lev") or "").strip().upper()
    scope = (m.group("scope") or "").strip()[:120]
    if source_tag:
        scope = f"{source_tag}/{scope}" if scope else source_tag
    msg = _with_multiline_msg(m.group("msg") or "", remainder)
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


def _remember_log_entry(entry: dict[str, Any]) -> None:
    with _entries_lock:
        _entry_ring.append(dict(entry))


def replay_log_entries_after(
    last_event_id: int,
    scope: LogScope,
    *,
    source: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    with _entries_lock:
        items = list(_entry_ring)
    out: list[dict[str, Any]] = []
    for entry in items:
        eid = int(entry.get("id") or 0)
        if eid <= last_event_id:
            continue
        if scope == "webui" and not str(entry.get("scope") or "").startswith(("pb_webui", "pallas_webui")):
            if "[pallas-webui]" not in str(entry.get("message") or ""):
                continue
        if scope == "protocol" and not str(entry.get("scope") or "").startswith(("pb_protocol", "pallas_protocol")):
            if "[pallas-protocol]" not in str(entry.get("message") or ""):
                continue
        if not _entry_matches_log_source(entry, source):
            continue
        out.append(dict(entry))
        if len(out) >= limit:
            break
    return fill_missing_log_entry_times(out)


def _normalize_log_source_key(tag: str) -> str:
    """分片来源归一：仅 ``worker-N`` / ``hub``；其余视为无来源标签。"""
    primary = (tag or "").strip().split("/", 1)[0]
    if primary.startswith("worker-"):
        return primary
    if primary in ("hub", "hub-file"):
        return "hub"
    return ""


def _log_source_key_from_raw_line(raw: str) -> str:
    first = raw.split("\n", 1)[0]
    tag, _ = _strip_shard_log_prefix(first)
    return _normalize_log_source_key(tag)


def _log_source_key_from_entry(entry: dict[str, Any]) -> str:
    scope = str(entry.get("scope") or "").strip()
    if scope:
        key = _normalize_log_source_key(scope.split("/", 1)[0])
        if key:
            return key
    msg = str(entry.get("message") or "")
    return _log_source_key_from_raw_line(msg)


def _raw_line_accepts_traceback_continuation(raw: str) -> bool:
    """跨 worker 交错时，仅把 traceback 续行吸回同来源的 error / 已有栈块。"""
    _, body = _strip_shard_log_prefix(raw)
    head = body.split("\n", 1)[0]
    if "Traceback" in body:
        return True
    if (
        _is_traceback_body(head)
        and not _log_line_re.match(head.lstrip())
        and not _nonebot_bracket_re.match(head.lstrip())
    ):
        # 已是栈帧/异常行块
        return True
    m = _log_line_re.match(head)
    if m and (m.group("lev") or "").strip().upper() in ("ERROR", "CRITICAL"):
        return True
    m3 = _nonebot_bracket_re.match(head)
    if m3 and (m3.group("lev") or "").strip().upper() in ("ERROR", "CRITICAL"):
        return True
    m2 = _stdlib_log_re.match(head)
    if m2 and (m2.group("lev") or "").strip().upper() in ("ERROR", "CRITICAL"):
        return True
    return False


def _entry_accepts_traceback_continuation(entry: dict[str, Any]) -> bool:
    if str(entry.get("level") or "") == "error":
        return True
    msg = str(entry.get("message") or "")
    return "Traceback" in msg or _is_traceback_body(msg)


def _entry_is_traceback_fragment(entry: dict[str, Any], msg: str) -> bool:
    """解析后异常行正文可能只剩消息（如 boom），仍视为 traceback 碎片。"""
    if _is_traceback_body(msg):
        return True
    if str(entry.get("level") or "") != "error":
        return False
    if str(entry.get("time") or "").strip():
        return False
    from pallas.core.platform.shard.logs.view import _is_log_header_body

    return not _is_log_header_body(msg)


def fill_missing_log_entry_times(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """无时间戳续行继承同来源上一条时间，避免多 worker 交错串台。"""
    last_by_source: dict[str, str] = {}
    last_any = ""
    for e in entries:
        key = _log_source_key_from_entry(e)
        t = str(e.get("time") or "").strip()
        if t:
            last_any = t
            if key:
                last_by_source[key] = t
        else:
            inherit = last_by_source.get(key) if key else last_any
            if inherit:
                e["time"] = inherit
    return entries


def merge_log_line_continuations(lines: list[str]) -> list[str]:
    """合并 traceback / pretty-print 等多行续行，避免结构化视图拆成多条 info。

    同来源相邻续行照常合并；``source=all`` 下多 worker 时间交错时，traceback 续行
    会吸回该 worker 最近一条 error/栈块，而不会粘到其他 worker 的 info。
    """
    from pallas.core.platform.shard.logs.view import _is_log_continuation_body

    out: list[str] = []
    last_idx_by_source: dict[str, int] = {}
    for line in lines:
        raw = line.rstrip("\n")
        if not raw.strip():
            continue
        tag, body = _strip_shard_log_prefix(raw)
        key = _normalize_log_source_key(tag)
        if not _is_log_continuation_body(body):
            out.append(raw)
            if key:
                last_idx_by_source[key] = len(out) - 1
            continue
        merged = False
        if out:
            prev_key = _log_source_key_from_raw_line(out[-1])
            if key and prev_key == key:
                out[-1] = f"{out[-1]}\n{raw}"
                merged = True
            elif not key and not prev_key:
                out[-1] = f"{out[-1]}\n{raw}"
                merged = True
            elif key and _is_traceback_body(body):
                idx = last_idx_by_source.get(key)
                if idx is not None and _raw_line_accepts_traceback_continuation(out[idx]):
                    out[idx] = f"{out[idx]}\n{raw}"
                    merged = True
        if not merged:
            out.append(raw)
            if key:
                last_idx_by_source[key] = len(out) - 1
    return out


def merge_log_entry_continuations(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from pallas.core.platform.shard.logs.view import _is_log_continuation_body

    out: list[dict[str, Any]] = []
    last_idx_by_source: dict[str, int] = {}
    rank = {"debug": 0, "info": 1, "success": 2, "warn": 3, "error": 4}

    def absorb(prev: dict[str, Any], cur: dict[str, Any]) -> None:
        prev_msg = str(prev.get("message") or "")
        msg = str(cur.get("message") or "")
        prev["message"] = f"{prev_msg}\n{msg}" if prev_msg else msg
        pl = str(prev.get("level") or "info")
        cl = str(cur.get("level") or "info")
        if rank.get(cl, 1) > rank.get(pl, 1):
            prev["level"] = cl

    for e in entries:
        cur = dict(e)
        msg = str(cur.get("message") or "")
        key = _log_source_key_from_entry(cur)
        is_cont = _is_log_continuation_body(msg) or _entry_is_traceback_fragment(cur, msg)
        if not is_cont:
            out.append(cur)
            if key:
                last_idx_by_source[key] = len(out) - 1
            continue
        merged = False
        if out:
            prev = out[-1]
            prev_key = _log_source_key_from_entry(prev)
            if key and prev_key == key:
                absorb(prev, cur)
                merged = True
            elif not key and not prev_key:
                absorb(prev, cur)
                merged = True
            elif key and _entry_is_traceback_fragment(cur, msg):
                idx = last_idx_by_source.get(key)
                if idx is not None and _entry_accepts_traceback_continuation(out[idx]):
                    absorb(out[idx], cur)
                    merged = True
        if not merged:
            out.append(cur)
            if key:
                last_idx_by_source[key] = len(out) - 1
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
    last_event_id: int | None = None,
) -> AsyncIterator[str]:
    """SSE：首包 ``ready``，随后 JSON 条目；支持 Last-Event-ID 断点续传。"""
    replay_from = int(last_event_id or 0)
    if replay_from > 0:
        for entry in replay_log_entries_after(replay_from, scope, source=source):
            yield f"id: {entry.get('id')}\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n"
    q, unsub = subscribe_nonebot_log_stream()
    shard_tailer = None
    try:
        from pallas.core.platform.bot_runtime.roles import is_sharded_hub

        if is_sharded_hub():
            from pallas.core.platform.shard.logs.view import ShardLogTailer

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
                            payload_entry = filled[0]
                            entry_id = payload_entry.get("id")
                            entry_json = json.dumps(payload_entry, ensure_ascii=False)
                            yield f"id: {entry_id}\ndata: {entry_json}\n\n"
                            hub_sent = True

            shard_sent = False
            new_lines: list[str] = []
            if shard_tailer is not None:

                def _poll_shard() -> list[str]:
                    return shard_tailer.poll_new_lines(scope=scope)

                new_lines = await asyncio.to_thread(_poll_shard)
                # 按来源缓冲本轮增量，先合并同 worker 续行再吐出，避免多 worker 交错串台
                by_source: dict[str, list[str]] = {}
                order: list[str] = []
                for line in new_lines:
                    key = _log_source_key_from_raw_line(line) or "_untagged"
                    if key not in by_source:
                        by_source[key] = []
                        order.append(key)
                    by_source[key].append(line)
                last_time_by_source: dict[str, str] = {}
                for key in order:
                    for merged_line in merge_log_line_continuations(by_source[key]):
                        e = parse_nonebot_log_line(merged_line)
                        if not _entry_matches_log_source(e, source):
                            continue
                        t = str(e.get("time") or "").strip()
                        if t:
                            last_time_by_source[key] = t
                        elif last_time_by_source.get(key):
                            e["time"] = last_time_by_source[key]
                        yield f"id: {e.get('id')}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
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
        return name in ("pb_webui", "pallas_webui") or "[pallas-webui]" in mstr
    return name in ("pb_protocol", "pallas_protocol") or "[pallas-protocol]" in mstr


def _sink_dispatch(message: object) -> None:
    text = str(message).rstrip("\n")
    if not text:
        return
    record = getattr(message, "record", None)
    entry = parse_nonebot_log_line(text)
    _remember_log_entry(entry)
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
        from pallas.core.platform.bot_runtime.roles import is_sharded_hub

        if is_sharded_hub():
            from pallas.core.platform.shard.logs.view import merge_cluster_log_lines

            return merge_cluster_log_lines(n, scope, hub_ring_lines=base, source=source)
    except Exception:
        pass
    if want == "all":
        return base
    from pallas.core.platform.shard.logs.view import collect_shard_file_log_lines, prefix_log_source

    if want == "hub":
        return [prefix_log_source(line, "hub") for line in base]
    return collect_shard_file_log_lines(per_file=n, scope=scope, source=source)[-n:]
