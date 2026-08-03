from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_TRACE_LOCK = threading.Lock()
_MAX_LINES = 5000
_trace_state_path = ""
_trace_state_revision: tuple[int, int] | None = None
_trace_state_line_count: int | None = None


def repeater_opportunity_trace_path() -> Path:
    return plugin_data_dir("pb_webui", create=True) / "repeater_opportunity_trace.jsonl"


def _trace_path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _trace_revision(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _trace_line_count(path: Path) -> int:
    global _trace_state_path, _trace_state_revision, _trace_state_line_count
    path_key = _trace_path_key(path)
    revision = _trace_revision(path)
    if _trace_state_path == path_key and _trace_state_revision == revision and _trace_state_line_count is not None:
        return _trace_state_line_count
    try:
        line_count = len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0
    except (OSError, UnicodeDecodeError):
        line_count = 0
    _trace_state_path = path_key
    _trace_state_revision = _trace_revision(path)
    _trace_state_line_count = line_count
    return line_count


def _note_trace_append(path: Path, line_count: int) -> None:
    global _trace_state_path, _trace_state_revision, _trace_state_line_count
    _trace_state_path = _trace_path_key(path)
    _trace_state_revision = _trace_revision(path)
    _trace_state_line_count = line_count


@contextmanager
def interprocess_trace_lock(path: Path) -> Iterator[None]:
    """跨 hub/worker 互斥，避免共用固定 .tmp 时 os.replace 竞态。"""
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        yield


def append_repeater_opportunity_trace(row: dict[str, Any]) -> bool:
    payload = {
        "ts": int(time.time()),
        **dict(row or {}),
    }
    line = json.dumps(payload, ensure_ascii=False)
    path = repeater_opportunity_trace_path()
    with _TRACE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with interprocess_trace_lock(path):
                line_count = _trace_line_count(path)
                if line_count < _MAX_LINES:
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(line + "\n")
                    _note_trace_append(path, line_count + 1)
                else:
                    previous = path.read_text(encoding="utf-8").splitlines()
                    previous = previous[-(_MAX_LINES - 1) :]
                    previous.append(line)
                    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
                    try:
                        tmp.write_text("\n".join(previous) + "\n", encoding="utf-8")
                        tmp.replace(path)
                    finally:
                        try:
                            tmp.unlink(missing_ok=True)
                        except OSError:
                            pass
                    _note_trace_append(path, len(previous))
            return True
        except OSError:
            # 埋点失败不应打断消息处理
            return False


def read_recent_repeater_opportunity_trace(*, limit: int = 200) -> list[dict[str, Any]]:
    path = repeater_opportunity_trace_path()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, int(limit)) :]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_conversation_decision_trace(trace_row: dict[str, Any]) -> bool:
    payload = dict(trace_row or {})
    payload.setdefault("kind", "conversation_decision_trace")
    return append_repeater_opportunity_trace(payload)
