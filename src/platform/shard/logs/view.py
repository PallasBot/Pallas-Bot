"""分片 hub：合并各 worker/hub 落盘日志尾行，供 WebUI /pallas/api/logs 与 log_error_log 读取。"""

from __future__ import annotations

import re
import time
from datetime import datetime
from operator import itemgetter
from typing import Any

from src.foundation.paths import plugin_data_dir

_PLUGIN = "pallas_shard"
_LOG_DIR_NAME = "logs"

_LOG_LINE_RE = re.compile(
    r"^(?P<dt>\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (?P<lev>\S+)\s* \| (?P<scope>[^:]+):(?P<lineno>\d+) - (?P<msg>.*)$",
)
_MERGE_DEDUPE_RE = re.compile(
    r"^(?P<head>\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| \S+\s* \| )(?:\[[^\]]+\] )?(?P<tail>.+)$",
)
_TS_PIPE = re.compile(r"^(?P<dt>\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_TS_BRACKET = re.compile(r"^(?P<dt>\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[")
_TS_ISO = re.compile(r"^(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_STDERR_ERROR_RE = re.compile(
    r"^(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - (?P<lev>ERROR|CRITICAL) - (?P<msg>.*)$",
)
_LOGURU_ERROR_RE = re.compile(
    r"^(?P<dt>\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (?P<lev>ERROR|CRITICAL)\s* \| "
    r"(?P<scope>[^:]+):(?P<lineno>\d+) - (?P<msg>.*)$",
)
_NONE_BOT_ERROR_RE = re.compile(
    r"^(?P<dt>\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(?P<lev>ERROR|CRITICAL)\] (?P<scope>[^|]+) \| (?P<msg>.*)$",
)
_STDIO_MIRROR_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ - (?P<lev>\w+) - (?P<msg>.*)$",
)
_WORKER_MAIN_LOG_RE = re.compile(r"^worker-\d+\.log$")


def shard_logs_dir():
    return plugin_data_dir(_PLUGIN, create=False) / _LOG_DIR_NAME


def shard_log_stem_in_registry_use(reg: Any, shard: Any) -> bool:
    """注册表内且已分配牛牛的 worker 分片；hub 角色除外。"""
    role = (shard.role or "normal").strip().lower()
    if role == "hub":
        return False
    return reg.count_on_shard(int(shard.id)) > 0


def registry_worker_log_stems() -> frozenset[str] | None:
    """分片开启时：注册表内已挂牛的 worker 日志 stem；未开分片返回 None。"""
    try:
        from src.platform.shard import context as shard_ctx
        from src.platform.shard.registry.store import get_shard_registry

        if not shard_ctx.sharding_active():
            return None
        reg = get_shard_registry()
        stems: set[str] = set()
        for shard in reg.shards:
            if not shard_log_stem_in_registry_use(reg, shard):
                continue
            stems.add(f"worker-{int(shard.id)}")
        return frozenset(stems)
    except Exception:
        return None


def worker_log_stem_allowed(stem: str) -> bool:
    """未在注册表在用列表中的 worker 落盘日志不参与合并/来源列表。"""
    allowed = registry_worker_log_stems()
    if allowed is None:
        return True
    return stem in allowed


def list_shard_log_sources() -> list[str]:
    """可供 WebUI 筛选的日志来源。"""
    out = ["hub"]
    root = shard_logs_dir()
    if not root.is_dir():
        return out
    for path in sorted(root.glob("worker-*.log")):
        if not _WORKER_MAIN_LOG_RE.match(path.name):
            continue
        stem = path.stem
        if worker_log_stem_allowed(stem):
            out.append(stem)
    return out


def _iter_shard_log_paths(source: str | None = None) -> list[tuple[Any, str]]:
    root = shard_logs_dir()
    if not root.is_dir():
        return []
    want = (source or "all").strip() or "all"
    paths: list[tuple[Any, str]] = []
    hub_log = root / "hub.log"
    if hub_log.is_file() and want in ("all", "hub", "hub-file"):
        paths.append((hub_log, "hub-file"))
    for path in sorted(root.glob("worker-*.log")):
        if not _WORKER_MAIN_LOG_RE.match(path.name):
            continue
        stem = path.stem
        if not worker_log_stem_allowed(stem):
            continue
        if want not in ("all", stem):
            continue
        paths.append((path, stem))
    return paths


def _line_matches_source(line: str, source: str | None) -> bool:
    want = (source or "all").strip() or "all"
    if want == "all":
        return True
    raw = line.strip()
    if want == "hub":
        return raw.startswith(("[hub]", "[hub-file]"))
    return f"[{want}]" in raw[:32]


def _extract_line_dt(body: str) -> str | None:
    raw = body.strip()
    m = _LOG_LINE_RE.match(raw)
    if m:
        return m.group("dt")
    m2 = _TS_BRACKET.match(raw)
    if m2:
        return m2.group("dt")
    m3 = _TS_ISO.match(raw)
    if m3:
        return m3.group("dt")
    m4 = _TS_PIPE.match(raw)
    if m4:
        return m4.group("dt")
    m5 = _STDERR_ERROR_RE.match(raw)
    if m5:
        iso = m5.group("dt")
        try:
            dt = datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%m-%d %H:%M:%S")
        except ValueError:
            return iso
    return None


def _is_log_header_body(body: str) -> bool:
    raw = body.strip()
    if _LOG_LINE_RE.match(raw):
        return True
    if _NONE_BOT_ERROR_RE.match(raw):
        return True
    if _STDIO_MIRROR_RE.match(raw):
        return True
    if _STDERR_ERROR_RE.match(raw):
        return True
    if _TS_BRACKET.match(raw):
        return True
    if _TS_ISO.match(raw):
        return True
    return False


def _is_log_continuation_body(body: str) -> bool:
    s = body.strip()
    if not s:
        return True
    if _is_log_header_body(s):
        return False
    if s.startswith("Traceback"):
        return True
    if s.startswith(("  File ", "    ", "\t")):
        return True
    if re.match(r"^[A-Z][a-zA-Z0-9_]*(?:Error|Exception):", s):
        return True
    if s.startswith("During handling of the above exception"):
        return True
    if re.match(r"^[\|└├╭╰─]", s):
        return True
    if re.match(r"^\|\s", s) or " L " in s[:16] or s.startswith("L "):
        return True
    if s.startswith("..."):
        return True
    if re.match(r"^\s+\S", s):
        return True
    return False


def _line_sort_key(line: str) -> tuple[str, str, int]:
    body = _line_body_without_shard_tag(line)
    dt = _extract_line_dt(body)
    if dt:
        return ("a", dt, 0)
    if _is_log_continuation_body(body):
        return ("z", body, 0)
    return ("y", body, 0)


def _lines_with_sort_keys(lines: list[str]) -> list[tuple[str, tuple[str, str, int]]]:
    """无时间戳的 traceback/异常续行继承上一条带时间戳日志的排序键，避免全局排序时被甩到文件末尾。"""
    keyed: list[tuple[str, tuple[str, str, int]]] = []
    last_dt = ""
    cont_seq = 0
    for line in lines:
        body = _line_body_without_shard_tag(line)
        dt = _extract_line_dt(body)
        if dt:
            last_dt = dt
            cont_seq = 0
            keyed.append((line, ("a", dt, 0)))
            continue
        if _is_log_continuation_body(body) and last_dt:
            cont_seq += 1
            keyed.append((line, ("a", last_dt, cont_seq)))
            continue
        keyed.append((line, _line_sort_key(line)))
    return keyed


def prefix_log_source(line: str, source: str) -> str:
    raw = line.rstrip("\n")
    if not raw:
        return raw
    m = _LOG_LINE_RE.match(raw.strip())
    if m:
        return (
            f"{m.group('dt')} | {m.group('lev')} | [{source}] {m.group('scope')}:{m.group('lineno')} - {m.group('msg')}"
        )
    return f"[{source}] {raw}"


def _line_matches_scope(line: str, scope: str) -> bool:
    if scope == "all":
        return True
    low = line.lower()
    if scope == "webui":
        return "pallas_webui" in low or "[pallas-webui]" in low
    if scope == "protocol":
        return "pallas_protocol" in low or "[pallas-protocol]" in low
    return True


def tail_log_file(path, max_lines: int) -> list[str]:
    if max_lines <= 0 or not path.is_file():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            chunk = min(size, max(max_lines * 400, 262144))
            fh.seek(max(0, size - chunk))
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = [ln for ln in data.splitlines() if ln.strip()]
    return lines[-max_lines:]


def collect_shard_file_log_lines(
    *,
    per_file: int,
    scope: str,
    source: str | None = None,
) -> list[str]:
    out: list[str] = []
    for path, tag in _iter_shard_log_paths(source):
        for line in tail_log_file(path, per_file):
            if not _line_matches_scope(line, scope):
                continue
            out.append(prefix_log_source(line, tag))
    return out


def _line_body_without_shard_tag(line: str) -> str:
    raw = line.strip()
    if raw.startswith("[") and "] " in raw[:40]:
        return raw.split("] ", 1)[1]
    return raw


def _merge_dedupe_key(line: str) -> str:
    body = _line_body_without_shard_tag(line).strip()
    if not body:
        return ""
    m = _MERGE_DEDUPE_RE.match(body)
    if m:
        return m.group("head") + m.group("tail")
    return body


def _line_message_tail(body: str) -> str:
    m = _LOG_LINE_RE.match(body.strip())
    if m:
        return m.group("msg") or ""
    m2 = _STDIO_MIRROR_RE.match(body.strip())
    if m2:
        return m2.group("msg") or ""
    m3 = _NONE_BOT_ERROR_RE.match(body.strip())
    if m3:
        return m3.group("msg") or ""
    return body.strip()


def dedupe_mirror_stdio_lines(lines: list[str]) -> list[str]:
    """去掉 loguru 行后紧跟的 stdlib 镜像行。"""
    out: list[str] = []
    prev_tail = ""
    for line in lines:
        body = _line_body_without_shard_tag(line)
        tail = _line_message_tail(body)
        if _STDIO_MIRROR_RE.match(body.strip()) and tail and tail == prev_tail:
            continue
        if not _STDIO_MIRROR_RE.match(body.strip()):
            prev_tail = tail
        out.append(line)
    return out


def dedupe_log_lines_preserve_order(lines: list[str]) -> list[str]:
    """去掉完全相同的行。"""
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def merge_cluster_log_lines(
    n: int,
    scope: str,
    *,
    hub_ring_lines: list[str],
    source: str | None = None,
) -> list[str]:
    """hub 内存环 + 分片落盘日志合并排序后取尾 n 行。"""
    if n <= 0:
        return []
    want = (source or "all").strip() or "all"
    paths = _iter_shard_log_paths(source)
    file_count = max(len(paths) + (1 if want in ("all", "hub") else 0), 1)
    per_file = min(max(n // file_count, 40), 1500)
    if file_count >= 6:
        per_file = min(per_file, max(48, n // max(file_count, 1)))
    keyed_bucket: list[tuple[str, tuple[str, str, int]]] = []
    if want in ("all", "hub"):
        hub_lines: list[str] = []
        for line in hub_ring_lines:
            if not _line_matches_scope(line, scope):
                continue
            if want != "all" and not _line_matches_source(prefix_log_source(line, "hub"), source):
                continue
            hub_lines.append(prefix_log_source(line, "hub"))
        hub_lines = dedupe_mirror_stdio_lines(hub_lines)
        keyed_bucket.extend(_lines_with_sort_keys(hub_lines))
    for path, tag in _iter_shard_log_paths(source):
        file_lines: list[str] = []
        for line in tail_log_file(path, per_file):
            if not _line_matches_scope(line, scope):
                continue
            file_lines.append(prefix_log_source(line, tag))
        file_lines = dedupe_mirror_stdio_lines(file_lines)
        keyed_bucket.extend(_lines_with_sort_keys(file_lines))
    if not keyed_bucket:
        return []
    seen: set[str] = set()
    deduped: list[tuple[str, tuple[str, str, int]]] = []
    for line, sort_key in keyed_bucket:
        key = _merge_dedupe_key(line)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append((line, sort_key))
    deduped.sort(key=itemgetter(1))
    return [line for line, _ in deduped[-n:]]


def _mmdd_hms_to_unix(mmdd_hms: str) -> int:
    try:
        mo, rest = mmdd_hms.split("-", 1)
        day, hm = rest.split(" ", 1)
        h, mi, s = hm.split(":")
        now = datetime.now()
        dt = datetime(now.year, int(mo), int(day), int(h), int(mi), int(s))
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0


def _iso_hms_to_unix(iso_hms: str) -> int:
    try:
        dt = datetime.strptime(iso_hms[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0


def _scope_short_name(scope: str) -> str:
    raw = (scope or "").strip()
    if not raw:
        return "log"
    parts = raw.replace(":", "/").split("/")
    for part in reversed(parts):
        if part and part != "__init__":
            return part
    return raw[:80]


def _plugin_label(source: str, scope: str) -> str:
    short = _scope_short_name(scope)
    if source in ("hub", "hub-file"):
        return short
    return f"{source}/{short}" if short else source


_EXC_TYPE_LINE_RE = re.compile(r"^([A-Z][a-zA-Z0-9_]*(?:Error|Exception))\s*:\s*(.*)$")


def _exc_type_and_message_from_traceback(tb: str) -> tuple[str, str]:
    """从 traceback 末行取标准异常类型与消息，避免误把栈帧代码行当类型。"""
    for line in reversed(tb.splitlines()):
        line = line.strip()
        if not line or line.startswith("Traceback"):
            continue
        if "└" in line or "│" in line:
            continue
        m = _EXC_TYPE_LINE_RE.match(line)
        if m:
            return m.group(1), (m.group(2) or "").strip()
    return "LogError", ""


def _exc_type_from_traceback(tb: str) -> str:
    return _exc_type_and_message_from_traceback(tb)[0]


def _parse_error_header_line(line: str) -> dict[str, Any] | None:
    raw = line.strip()
    if not raw:
        return None
    m = _STDERR_ERROR_RE.match(raw)
    if m:
        return {
            "at": _iso_hms_to_unix(m.group("dt")),
            "scope": "",
            "exc_type": "LogError",
            "message": m.group("msg") or "",
        }
    m = _LOGURU_ERROR_RE.match(raw)
    if m:
        return {
            "at": _mmdd_hms_to_unix(m.group("dt")),
            "scope": m.group("scope") or "",
            "exc_type": "LogError",
            "message": m.group("msg") or "",
        }
    m = _NONE_BOT_ERROR_RE.match(raw)
    if m:
        return {
            "at": _mmdd_hms_to_unix(m.group("dt")),
            "scope": (m.group("scope") or "").strip(),
            "exc_type": "LogError",
            "message": m.group("msg") or "",
        }
    return None


def _error_at_before(lines: list[str], idx: int) -> int:
    for k in range(idx - 1, max(-1, idx - 80), -1):
        header = _parse_error_header_line(lines[k])
        if header is not None:
            return int(header.get("at") or 0)
    return 0


def _collect_traceback_lines(lines: list[str], start: int) -> tuple[str, int]:
    tb_parts: list[str] = []
    j = start
    while j < len(lines):
        row = lines[j]
        if not row.strip():
            break
        if row.startswith(("Traceback", "  ", "\t")):
            tb_parts.append(row)
            j += 1
            continue
        if _parse_error_header_line(row) is not None:
            break
        if re.match(r"^[A-Z][a-zA-Z0-9_]*(?:Error|Exception):", row):
            tb_parts.append(row)
            j += 1
            break
        break
    return "\n".join(tb_parts), j


def _scan_log_file_errors(path, source: str, *, max_lines: int) -> list[dict[str, Any]]:
    lines = tail_log_file(path, max_lines)
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("Traceback"):
            tb, j = _collect_traceback_lines(lines, i)
            exc_type, msg = _exc_type_and_message_from_traceback(tb)
            out.append({
                "at": _error_at_before(lines, i),
                "plugin": source,
                "exc_type": exc_type,
                "message": msg[:2000],
                "traceback": tb,
            })
            i = j
            continue
        header = _parse_error_header_line(line)
        if header is None:
            i += 1
            continue
        tb, j = _collect_traceback_lines(lines, i + 1)
        exc_type = str(header["exc_type"] or "LogError")
        msg = str(header.get("message") or "")
        if tb:
            tb_exc, tb_msg = _exc_type_and_message_from_traceback(tb)
            if tb_exc != "LogError":
                exc_type = tb_exc
            if tb_msg:
                msg = tb_msg
        out.append({
            "at": int(header["at"] or 0),
            "plugin": _plugin_label(source, str(header.get("scope") or "")),
            "exc_type": exc_type,
            "message": msg[:2000],
            "traceback": tb,
        })
        i = j
    return out


def merge_error_rows_prefer_longer_tb(*rows: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for it in rows:
        if not isinstance(it, dict):
            continue
        key = (
            str(it.get("at") or 0),
            str(it.get("plugin") or ""),
            str(it.get("exc_type") or ""),
            str(it.get("message") or "")[:300],
        )
        prev = merged.get(key)
        if prev is None or len(str(it.get("traceback") or "")) > len(str(prev.get("traceback") or "")):
            merged[key] = dict(it)
    out = list(merged.values())
    out.sort(key=lambda x: int(x.get("at") or 0))
    return out


def collect_cluster_log_errors(
    *,
    per_file: int = 600,
    limit: int = 120,
) -> list[dict[str, Any]]:
    """合并分片 ERROR：jsonl 与落盘日志互补，traceback 取更长的一份。"""
    if limit <= 0:
        return []
    jsonl_rows: list[dict[str, Any]] = []
    skip_log_scan = False
    try:
        from src.platform.shard.logs.errors import (
            collect_cluster_log_errors_from_jsonl,
            errors_archive_prefers_jsonl_only,
            shard_errors_dir,
        )

        jsonl_rows = collect_cluster_log_errors_from_jsonl(limit=max(limit * 2, 80))
        skip_log_scan = False
        if shard_errors_dir().is_dir() and errors_archive_prefers_jsonl_only():
            # 已进入 jsonl 归档模式：只读 errors/*.jsonl，清理后勿再扫主日志
            skip_log_scan = True
    except Exception:
        skip_log_scan = False
    log_rows: list[dict[str, Any]] = []
    if not skip_log_scan:
        root = shard_logs_dir()
        if root.is_dir():
            scan_paths: list[tuple[Any, str]] = []
            hub_log = root / "hub.log"
            if hub_log.is_file():
                scan_paths.append((hub_log, "hub-file"))
            for path in sorted(root.glob("worker-*.log")):
                if not _WORKER_MAIN_LOG_RE.match(path.name):
                    continue
                stem = path.stem
                if not worker_log_stem_allowed(stem):
                    continue
                scan_paths.append((path, stem))
            for path, source in scan_paths:
                log_rows.extend(_scan_log_file_errors(path, source, max_lines=per_file))
    merged = merge_error_rows_prefer_longer_tb(*jsonl_rows, *log_rows)
    if not merged:
        return []
    return merged[-limit:]


def cleanup_stale_shard_log_files(
    *,
    bootstrap_max_age_days: int = 7,
    rotated_max_age_days: int = 30,
    trim_main_log_bytes: int = 80 * 1024 * 1024,
) -> list[str]:
    """hub 启动或定时任务：清理 bootstrap、过期轮转备份，必要时裁切超大主日志。"""
    root = shard_logs_dir()
    if not root.is_dir():
        return []
    removed: list[str] = []
    now = time.time()

    def try_remove(path) -> None:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass

    archive = root / "archive"
    if archive.is_dir():
        for path in archive.iterdir():
            if not path.is_file():
                continue
            try:
                if now - path.stat().st_mtime > rotated_max_age_days * 86400:
                    try_remove(path)
            except OSError:
                pass

    for path in root.glob("*.bootstrap.log"):
        try:
            age = now - path.stat().st_mtime
            if age > bootstrap_max_age_days * 86400 or path.stat().st_size == 0:
                try_remove(path)
        except OSError:
            pass

    for path in root.glob("*.log.*"):
        try:
            if now - path.stat().st_mtime > rotated_max_age_days * 86400:
                try_remove(path)
        except OSError:
            pass

    for path in root.glob("worker-*.log"):
        if not _WORKER_MAIN_LOG_RE.match(path.name):
            continue
        try:
            st = path.stat()
            if st.st_size > trim_main_log_bytes and now - st.st_mtime > 120:
                lines = tail_log_file(path, 8000)
                text = "".join(f"{ln}\n" for ln in lines)
                path.write_text(text, encoding="utf-8")
                removed.append(f"{path.name}:trimmed")
        except OSError:
            pass

    hub_log = root / "hub.log"
    if hub_log.is_file():
        try:
            st = hub_log.stat()
            if st.st_size > trim_main_log_bytes and now - st.st_mtime > 120:
                lines = tail_log_file(hub_log, 8000)
                hub_log.write_text("".join(f"{ln}\n" for ln in lines), encoding="utf-8")
                removed.append("hub.log:trimmed")
        except OSError:
            pass

    return removed


class ShardLogTailer:
    """分片 hub SSE：按文件偏移增量读取各 worker/hub 落盘日志。"""

    def __init__(self, *, source: str | None = None) -> None:
        self._source = (source or "all").strip() or "all"
        self._offsets: dict[str, int] = {}
        self._bootstrap_offsets()

    def _bootstrap_offsets(self) -> None:
        for path, _tag in _iter_shard_log_paths(self._source):
            key = str(path)
            try:
                self._offsets[key] = path.stat().st_size
            except OSError:
                self._offsets[key] = 0

    def poll_new_lines(self, *, scope: str) -> list[str]:
        out: list[str] = []
        for path, tag in _iter_shard_log_paths(self._source):
            key = str(path)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            start = self._offsets.get(key, 0)
            if size < start:
                start = 0
            if size <= start:
                continue
            try:
                with path.open("rb") as fh:
                    fh.seek(start)
                    chunk = fh.read(size - start).decode("utf-8", errors="replace")
            except OSError:
                continue
            self._offsets[key] = size
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                if not _line_matches_scope(line, scope):
                    continue
                out.append(prefix_log_source(line, tag))
        return out
