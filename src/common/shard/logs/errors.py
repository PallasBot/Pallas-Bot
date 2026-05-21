"""分片进程 ERROR/CRITICAL 结构化归档（hub + 各 worker 各一份 jsonl，hub WebUI 合并读取）。"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from src.common.shard.logs.view import shard_logs_dir

_ERRORS_DIR_NAME = "errors"
_APPEND_LOCK = threading.Lock()
_MSG_MAX = 2000
_TB_MAX = 50_000
_JSONL_MAX_BYTES = 2 * 1024 * 1024
_JSONL_TRIM_LINES = 200


def shard_errors_dir():
    root = shard_logs_dir() / _ERRORS_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def log_stem_for_shard(*, role: str, shard_id: int) -> str:
    if role == "hub":
        return "hub"
    return f"worker-{shard_id}"


def errors_jsonl_path(stem: str):
    return shard_errors_dir() / f"{stem}.jsonl"


def _dotted_module_short_name(module_name: str) -> str:
    parts = str(module_name or "").split(".")
    for part in reversed(parts):
        if part and part != "__init__":
            return part
    return str(module_name or "") or "unknown"


def _tb_and_exc_type_from_log_record(record: Any) -> tuple[str, str, str]:
    try:
        msg = str(record["message"])
    except Exception:
        msg = ""
    exc_type = "LogError"
    tb = ""
    try:
        exc = record["exception"]
    except Exception:
        exc = None
    if exc is not None:
        try:
            import traceback

            exc_type = type(exc.value).__name__
            tb = "".join(traceback.format_exception(type(exc.value), exc.value, exc.traceback))
        except Exception:
            tb = str(exc)
    return exc_type, msg, tb


def _plugin_label_for_record(stem: str, record: Any) -> str:
    try:
        full_name = str(record["name"] or "")
    except Exception:
        full_name = ""
    short = _dotted_module_short_name(full_name)
    if stem.startswith("worker-"):
        return f"{stem}/{short}" if short else stem
    return short or stem


def append_shard_log_error(entry: dict[str, Any], *, stem: str) -> None:
    path = errors_jsonl_path(stem)
    line_obj = {k: v for k, v in entry.items() if k != "raw_line"}
    line = json.dumps(line_obj, ensure_ascii=False) + "\n"
    with _APPEND_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        try:
            if path.stat().st_size > _JSONL_MAX_BYTES:
                rows = path.read_text(encoding="utf-8").splitlines()
                keep = rows[-_JSONL_TRIM_LINES:]
                path.write_text("".join(f"{r}\n" for r in keep if r.strip()), encoding="utf-8")
        except OSError:
            pass


def append_shard_log_error_from_sink(text: str, record: Any, *, stem: str) -> None:
    exc_type, msg, tb = _tb_and_exc_type_from_log_record(record)
    if len(tb) > _TB_MAX:
        tb = tb[:_TB_MAX] + "\n…(truncated)"
    if len(msg) > _MSG_MAX:
        msg = msg[:_MSG_MAX] + "…"
    if not msg.strip():
        msg = (text or "")[:_MSG_MAX]
        if len(text or "") > _MSG_MAX:
            msg = msg + "…"
    append_shard_log_error(
        {
            "at": int(time.time()),
            "plugin": _plugin_label_for_record(stem, record),
            "exc_type": exc_type,
            "message": msg,
            "traceback": tb,
        },
        stem=stem,
    )


def tail_errors_jsonl(path, *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in raw[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def collect_cluster_log_errors_from_jsonl(*, limit: int = 120) -> list[dict[str, Any]]:
    """读取 errors/*.jsonl 合并排序（优先于扫大日志文件）。"""
    root = shard_errors_dir()
    if not root.is_dir():
        return []
    paths = sorted(root.glob("*.jsonl"))
    per_file = max(limit, 40)
    bucket: list[dict[str, Any]] = []
    for path in paths:
        bucket.extend(tail_errors_jsonl(path, limit=per_file))
    if not bucket:
        return []
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for it in bucket:
        key = (
            str(it.get("plugin") or ""),
            str(it.get("exc_type") or ""),
            str(it.get("message") or "")[:300],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    deduped.sort(key=lambda x: int(x.get("at") or 0))
    return deduped[-limit:]


def cleanup_shard_error_archives_sync() -> None:
    root = shard_errors_dir()
    if not root.is_dir():
        return
    with _APPEND_LOCK:
        for path in root.glob("*.jsonl"):
            try:
                path.unlink()
            except OSError:
                pass
