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

from pallas.console.cli.log_paths import EMBED_AUX_LOG, WORK_AUX_LOG
from pallas.core.foundation.logging import REPO_FILE_LOG_FORMAT

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping
    from pathlib import Path

LogFacet = Literal["message", "console", "other"]
LogScope = Literal["all", "message", "console", "other"]

_LOG_ERROR_SINK_CB: Callable[[str, Mapping[str, Any]], None] | None = None

_CONSOLE_LOGGER_NAMES = frozenset({"pb_webui", "pallas_webui"})
AuxLogSource = Literal["work", "embed"]
AUX_LOG_PATHS: dict[AuxLogSource, Path] = {
    "work": WORK_AUX_LOG,
    "embed": EMBED_AUX_LOG,
}
_MESSAGE_SEND_API_RE = re.compile(
    r"Calling API send_(?:msg|group_msg|private_msg|group_forward_msg|private_forward_msg)\b",
    re.IGNORECASE,
)
_ACCESS_PALLAS_PATH_RE = re.compile(r'"[A-Z]+\s+/pallas(?:/|\s|")')


def set_log_error_capture(cb: Callable[[str, Mapping[str, Any]], None] | None) -> None:
    """由 pallas_webui 注册：在 NoneBot 日志 sink 中捕获 ERROR/CRITICAL 行并持久化。"""
    global _LOG_ERROR_SINK_CB
    _LOG_ERROR_SINK_CB = cb


_MAX = 20000
_lines: deque[str] = deque(maxlen=_MAX)
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
_nonebot_brace_re = re.compile(
    r"^(?P<dt>\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(?P<lev>\w+)\s*\] \{(?P<scope>[^}]*)\}\s*(?:\| )?(?P<msg>.*)$",
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
    多行块只剥每段行首的 ``[tag] ``（含合并后续行时残留的 tag）。
    """
    tags: list[str] = []
    body = raw.rstrip("\n")
    while True:
        first, sep, rest = body.partition("\n")
        m = _shard_source_prefix_re.match(first)
        if not m:
            break
        tags.append(m.group("tag"))
        body = m.group("body") + (f"{sep}{rest}" if sep else "")
    # 合并块内续行可能仍带 ``[tag] ``，剥掉以免正文里夹来源标签
    if tags and "\n" in body:
        tag_set = set(tags)
        rebuilt: list[str] = []
        for i, ln in enumerate(body.split("\n")):
            if i == 0:
                rebuilt.append(ln)
                continue
            m = _shard_source_prefix_re.match(ln)
            if m and m.group("tag") in tag_set:
                rebuilt.append(m.group("body"))
            else:
                rebuilt.append(ln)
        body = "\n".join(rebuilt)
    source_tag = tags[0] if len(tags) == 1 else "/".join(tags) if tags else ""
    return source_tag, body


_embedded_scope_tag_re = re.compile(r"^\[(?P<tag>[^\]]+)\]\s*(?P<mod>.*)$")


def _compose_log_scope(scope: str, source_tag: str) -> str:
    """合并来源标签与模块名；兼容 ``prefix_log_source`` 写入的 ``[worker-N] mod``。"""
    mod = (scope or "").strip()
    tag = (source_tag or "").strip()
    em = _embedded_scope_tag_re.match(mod)
    if em:
        embedded = (em.group("tag") or "").strip()
        mod = (em.group("mod") or "").strip()
        if not tag:
            tag = embedded
    if tag:
        return f"{tag}/{mod}" if mod else tag
    return mod


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
        m3 = _nonebot_brace_re.match(head) or _nonebot_bracket_re.match(head)
        if m3:
            lev_raw = (m3.group("lev") or "").strip().upper()
            scope = _compose_log_scope((m3.group("scope") or "").strip()[:120], source_tag)
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
    scope = _compose_log_scope((m.group("scope") or "").strip()[:120], source_tag)
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
        if not entry_matches_log_scope(entry, scope):
            continue
        if not _entry_matches_log_source(entry, source):
            continue
        out.append(dict(entry))
        if len(out) >= limit:
            break
    return fill_missing_log_entry_times(out)


def _normalize_log_source_key(tag: str) -> str:
    """日志来源归一：分片 hub/worker 与辅进程标签。"""
    primary = (tag or "").strip().split("/", 1)[0]
    if primary.startswith("worker-"):
        return primary
    if primary in ("hub", "hub-file"):
        return "hub"
    if primary in AUX_LOG_PATHS:
        return primary
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
                out[-1] = f"{out[-1]}\n{body}"
                merged = True
            elif not key and not prev_key:
                out[-1] = f"{out[-1]}\n{body}"
                merged = True
            elif key and _is_traceback_body(body):
                idx = last_idx_by_source.get(key)
                if idx is not None and _raw_line_accepts_traceback_continuation(out[idx]):
                    out[idx] = f"{out[idx]}\n{body}"
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
        entry = parse_nonebot_log_line(line, entry_id=-(i + 1))
        if "facet" not in entry:
            entry["facet"] = classify_log_facet(None, entry)
        out.append(entry)
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
    key = _log_source_key_from_entry(entry)
    if want in ("hub", "hub-file"):
        # hub 内存环常无前缀；落盘为 hub-file → 归一成 hub
        return key in ("", "hub")
    return key == want


def list_aux_log_sources() -> list[AuxLogSource]:
    """返回已有落盘日志的辅进程来源，避免未启用的 embed 出现在控制台。"""
    return [source for source, path in AUX_LOG_PATHS.items() if path.is_file()]


def _tail_aux_log_lines(n: int, scope: LogScope, source: str | None) -> list[str]:
    from pallas.core.platform.shard.logs.view import prefix_log_source, tail_log_file

    want = (source or "all").strip() or "all"
    out: list[str] = []
    for aux_source, path in AUX_LOG_PATHS.items():
        if want not in ("all", aux_source):
            continue
        lines = filter_log_lines_by_scope(tail_log_file(path, n), scope)
        out.extend(prefix_log_source(line, aux_source) for line in lines)
    return out


def merge_aux_log_lines(
    n: int,
    scope: LogScope,
    *,
    base_lines: list[str],
    source: str | None,
) -> list[str]:
    """将主进程或分片日志与辅进程落盘日志按时间合并。"""
    want = (source or "all").strip() or "all"
    lines = _tail_aux_log_lines(n, scope, source)
    if want in ("all", "hub"):
        if want == "hub":
            from pallas.core.platform.shard.logs.view import prefix_log_source

            lines.extend(prefix_log_source(line, "hub") for line in base_lines)
        else:
            lines.extend(base_lines)

    ordered = sorted(
        enumerate(lines),
        key=lambda item: (str(parse_nonebot_log_line(item[1], entry_id=0).get("time") or "~"), item[0]),
    )
    return [line for _, line in ordered[-n:]]


class AuxLogTailer:
    """WebUI SSE：按文件偏移增量读取 work / embed 辅进程日志。"""

    def __init__(self, *, source: str | None = None) -> None:
        self._source = (source or "all").strip() or "all"
        self._offsets: dict[str, int] = {}
        self._partial: dict[str, str] = {}
        self._bootstrap_offsets()

    def _iter_paths(self) -> list[tuple[Path, AuxLogSource]]:
        return [(path, aux_source) for aux_source, path in AUX_LOG_PATHS.items() if self._source in ("all", aux_source)]

    def _bootstrap_offsets(self) -> None:
        for path, _source in self._iter_paths():
            try:
                self._offsets[str(path)] = path.stat().st_size
            except OSError:
                self._offsets[str(path)] = 0

    def poll_new_lines(self, *, scope: LogScope) -> list[str]:
        from pallas.core.platform.shard.logs.view import prefix_log_source

        out: list[str] = []
        for path, aux_source in self._iter_paths():
            key = str(path)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            start = self._offsets.get(key, 0)
            if size < start:
                start = 0
                self._partial.pop(key, None)
            if size <= start:
                continue
            try:
                with path.open("rb") as fh:
                    fh.seek(start)
                    chunk = fh.read(size - start).decode("utf-8", errors="replace")
            except OSError:
                continue
            self._offsets[key] = size
            data = self._partial.pop(key, "") + chunk
            if chunk and not chunk.endswith(("\n", "\r")):
                head, sep, rem = data.rpartition("\n")
                if sep:
                    complete = head
                    self._partial[key] = rem
                else:
                    self._partial[key] = data
                    continue
            else:
                complete = data
            out.extend(
                prefix_log_source(line, aux_source) for line in filter_log_lines_by_scope(complete.splitlines(), scope)
            )
        return out


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
    aux_tailer = AuxLogTailer(source=source)
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
                entry = payload.get("entry")
                if isinstance(entry, dict) and entry_matches_log_scope(entry, scope):
                    if _entry_matches_log_source(entry, source):
                        filled = fill_missing_log_entry_times([dict(entry)])
                        payload_entry = filled[0]
                        entry_id = payload_entry.get("id")
                        entry_json = json.dumps(payload_entry, ensure_ascii=False)
                        yield f"id: {entry_id}\ndata: {entry_json}\n\n"
                        hub_sent = True

            file_sent = False
            new_lines: list[str] = []
            if shard_tailer is not None:

                def _poll_shard() -> list[str]:
                    return shard_tailer.poll_new_lines(scope=scope)

                new_lines = await asyncio.to_thread(_poll_shard)
            if aux_tailer is not None:

                def _poll_aux() -> list[str]:
                    return aux_tailer.poll_new_lines(scope=scope)

                new_lines.extend(await asyncio.to_thread(_poll_aux))
            if new_lines:
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
                        e["facet"] = classify_log_facet(None, e)
                        if not entry_matches_log_scope(e, scope):
                            continue
                        if not _entry_matches_log_source(e, source):
                            continue
                        t = str(e.get("time") or "").strip()
                        if t:
                            last_time_by_source[key] = t
                        elif last_time_by_source.get(key):
                            e["time"] = last_time_by_source[key]
                        yield f"id: {e.get('id')}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                        file_sent = True

            if not hub_sent and not file_sent:
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


def _logger_name_from_record_or_entry(
    record: Mapping[str, Any] | Any | None,
    entry: Mapping[str, Any] | None,
) -> str:
    if record is not None:
        try:
            name = str(record.get("name") or "").strip()
        except Exception:
            name = str(getattr(record, "name", "") or "").strip()
        if name:
            return name
    if entry is not None:
        scope = str(entry.get("scope") or "").strip()
        if "/" in scope:
            scope = scope.rsplit("/", 1)[-1]
        return scope
    return ""


def _message_text_from_record_or_entry(
    record: Mapping[str, Any] | Any | None,
    entry: Mapping[str, Any] | None,
) -> str:
    if record is not None:
        try:
            raw = record.get("message")
        except Exception:
            raw = None
        if isinstance(raw, str):
            return raw
    if entry is not None:
        return str(entry.get("message") or "")
    return ""


def classify_log_facet(
    record: Mapping[str, Any] | Any | None,
    entry: Mapping[str, Any] | None,
) -> LogFacet:
    """将日志条目归类为 message / console / other（优先级：console → message → other）。"""
    name = _logger_name_from_record_or_entry(record, entry)
    msg = _message_text_from_record_or_entry(record, entry)

    if name in _CONSOLE_LOGGER_NAMES or "[pallas-webui]" in msg:
        return "console"
    if name == "uvicorn.access" or name.startswith("uvicorn.access"):
        if "/pallas/" in msg or "/pallas " in msg or msg.rstrip().endswith("/pallas"):
            return "console"
    if _ACCESS_PALLAS_PATH_RE.search(msg):
        return "console"

    if "ready to send" in msg:
        return "message"
    if "[message." in msg or "[Bot " in msg:
        return "message"
    if "Matcher(type='message'" in msg or 'Matcher(type="message"' in msg:
        return "message"
    if _MESSAGE_SEND_API_RE.search(msg):
        return "message"
    if name.startswith("nonebot.adapters.onebot") and ("Message " in msg and " from " in msg):
        return "message"

    return "other"


def resolve_entry_facet(entry: Mapping[str, Any] | None) -> LogFacet:
    """读取条目 facet；缺失时视为 other（旧日志不回填）。"""
    if not entry:
        return "other"
    raw = entry.get("facet")
    if raw in ("message", "console", "other"):
        return raw  # type: ignore[return-value]
    return "other"


def entry_matches_log_scope(entry: Mapping[str, Any] | None, scope: LogScope | str) -> bool:
    if scope == "all":
        return True
    if scope not in ("message", "console", "other"):
        return True
    return resolve_entry_facet(entry) == scope


def nonebot_log_record_matches_http_facet(
    record: Mapping[str, Any],
    facet: Literal["webui", "protocol", "console", "message", "other"],
) -> bool:
    """兼容旧调用：webui→console；protocol 不再单独切面，恒为 False。"""
    classified = classify_log_facet(record, None)
    if facet in ("webui", "console"):
        return classified == "console"
    if facet == "message":
        return classified == "message"
    if facet == "other":
        return classified == "other"
    return False


def _sink_dispatch(message: object) -> None:
    text = str(message).rstrip("\n")
    if not text:
        return
    record = getattr(message, "record", None)
    entry = parse_nonebot_log_line(text)
    facet = classify_log_facet(record, entry)
    entry["facet"] = facet
    _remember_log_entry(entry)
    payload = {
        "entry": entry,
        "scopes": {
            "all": True,
            "message": facet == "message",
            "console": facet == "console",
            "other": facet == "other",
        },
    }
    with _lock:
        _lines.append(text)
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
        format=REPO_FILE_LOG_FORMAT,
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


def filter_log_lines_by_scope(lines: list[str], scope: LogScope | str) -> list[str]:
    """按 facet 过滤原始行；无 facet 时用 classify 从行文推断（file merge）；推断不出则 other。"""
    if scope == "all":
        return list(lines)
    out: list[str] = []
    for line in lines:
        entry = parse_nonebot_log_line(line, entry_id=0)
        facet = classify_log_facet(None, entry)
        if facet == scope:
            out.append(line)
    return out


def tail_nonebot_log_lines_scoped(
    n: int,
    scope: LogScope,
    *,
    source: str | None = None,
) -> list[str]:
    want = (source or "all").strip() or "all"
    if scope == "all":
        base = tail_nonebot_log_lines(n)
    else:
        # 从主环过量取样再按 facet 过滤，避免窄范围时条数不足
        oversample = min(max(n * 8, n + 200), _MAX)
        with _lock:
            candidates = list(_lines)[-oversample:]
        base = filter_log_lines_by_scope(candidates, scope)[-n:]
    sharded = False
    try:
        from pallas.core.platform.bot_runtime.roles import is_sharded_hub

        sharded = is_sharded_hub()
        if sharded:
            from pallas.core.platform.shard.logs.view import merge_cluster_log_lines

            base = merge_cluster_log_lines(n, scope, hub_ring_lines=base, source=source)
    except Exception:
        pass
    if not sharded and want not in ("all", "hub", *AUX_LOG_PATHS):
        from pallas.core.platform.shard.logs.view import collect_shard_file_log_lines

        base = collect_shard_file_log_lines(per_file=n, scope=scope, source=source)[-n:]
    return merge_aux_log_lines(n, scope, base_lines=base, source=source)
