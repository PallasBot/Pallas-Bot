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


def repeater_opportunity_trace_path() -> Path:
    return plugin_data_dir("pb_webui", create=True) / "repeater_opportunity_trace.jsonl"


@contextmanager
def interprocess_trace_lock(path: Path) -> Iterator[None]:
    """跨 hub/worker 互斥，避免共用固定 .tmp 时 os.replace 竞态。"""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


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
                try:
                    previous = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
                except (OSError, UnicodeDecodeError):
                    previous = []
                previous.append(line)
                if len(previous) > _MAX_LINES:
                    previous = previous[-_MAX_LINES:]
                # 分片下多进程不可共用固定 .tmp，否则 replace 会 FileNotFoundError
                tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
                try:
                    tmp.write_text("\n".join(previous) + "\n", encoding="utf-8")
                    tmp.replace(path)
                finally:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
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
