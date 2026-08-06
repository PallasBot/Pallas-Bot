from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from .data_dir import pb_webui_data_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

INGRESS_HISTORY_RETENTION_SEC = 7 * 24 * 60 * 60
_COUNTER_KEYS = ("group_messages", "learn_enqueued", "learn_persisted", "work_completed")
_HISTORY_LOCK = threading.Lock()
_last_prune_at = 0


def ingress_metrics_history_path() -> Path:
    return pb_webui_data_dir() / "ingress_metrics_history.jsonl"


@contextmanager
def _interprocess_history_lock(path: Path) -> Iterator[None]:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        yield


def _number(value: Any) -> float | int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _sample(snapshot: dict[str, Any], *, ts: int) -> dict[str, Any]:
    scheduler = snapshot.get("conversation_scheduler")
    scheduler = scheduler if isinstance(scheduler, dict) else {}
    work = snapshot.get("work_aux") if isinstance(snapshot.get("work_aux"), dict) else {}
    hotpath = snapshot.get("hotpath") if isinstance(snapshot.get("hotpath"), dict) else {}
    return {
        "ts": int(ts),
        "ingress_p95_ms": _number(snapshot.get("ingress_duration_ms_p95")),
        "scheduler_wait_p95_ms": _number(scheduler.get("wait_ms_p95")),
        "scheduler_pending": int(scheduler.get("pending") or 0),
        "scheduler_active": int(scheduler.get("active") or 0),
        "scheduler_capacity": int(scheduler.get("concurrency") or 0),
        "work_pending": int(work.get("pending") or 0),
        "work_leased": int(work.get("leased") or 0),
        "group_messages": int(snapshot.get("group_messages") or 0),
        "learn_enqueued": int(hotpath.get("learn_enqueued") or 0),
        "learn_persisted": int(hotpath.get("learn_persisted") or 0),
        "work_completed": int(work.get("completed_since_start") or 0),
    }


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and isinstance(row.get("ts"), int):
            rows.append(row)
    return rows


def prune_ingress_metrics_history(*, now: int | None = None) -> bool:
    path = ingress_metrics_history_path()
    cutoff = int(now if now is not None else time.time()) - INGRESS_HISTORY_RETENTION_SEC
    with _HISTORY_LOCK:
        try:
            with _interprocess_history_lock(path):
                rows = [row for row in _read_rows(path) if int(row["ts"]) > cutoff]
                if not rows:
                    path.unlink(missing_ok=True)
                    return True
                path.parent.mkdir(parents=True, exist_ok=True)
                body = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
                path.write_text(body, encoding="utf-8")
                return True
        except OSError:
            return False


def append_ingress_metrics_history(*, snapshot: dict[str, Any], ts: int | None = None) -> bool:
    global _last_prune_at
    now = int(ts if ts is not None else time.time())
    path = ingress_metrics_history_path()
    row = _sample(snapshot, ts=now)
    with _HISTORY_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _interprocess_history_lock(path):
                with path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(row, separators=(",", ":")) + "\n")
        except OSError:
            return False
    if now - _last_prune_at >= 300:
        _last_prune_at = now
        prune_ingress_metrics_history(now=now)
    return True


def _counter_delta(current: dict[str, Any], previous: dict[str, Any] | None, key: str) -> int:
    value = int(current.get(key) or 0)
    if previous is None:
        return 0
    return max(0, value - int(previous.get(key) or 0))


def read_ingress_metrics_history(*, window_sec: int, bucket_sec: int, now: int | None = None) -> dict[str, Any]:
    now_sec = int(now if now is not None else time.time())
    window = max(60, min(INGRESS_HISTORY_RETENTION_SEC, int(window_sec)))
    bucket = max(15, min(3600, int(bucket_sec)))
    start = now_sec - window
    rows = sorted(_read_rows(ingress_metrics_history_path()), key=lambda row: int(row["ts"]))
    previous = next((row for row in reversed(rows) if int(row["ts"]) < start), None)
    points: dict[int, dict[str, Any]] = {}
    for row in rows:
        ts = int(row["ts"])
        if ts < start or ts > now_sec:
            previous = row
            continue
        at = ts - (ts % bucket)
        point = points.setdefault(
            at,
            {
                "at": at,
                "ingress_p95_ms": 0.0,
                "scheduler_wait_p95_ms": 0.0,
                "scheduler_pending": 0,
                "scheduler_active": 0,
                "scheduler_capacity": 0,
                "work_pending": 0,
                "work_leased": 0,
                **dict.fromkeys(_COUNTER_KEYS, 0),
            },
        )
        for key in ("ingress_p95_ms", "scheduler_wait_p95_ms"):
            point[key] = max(float(point[key]), float(row.get(key) or 0))
        for key in ("scheduler_pending", "scheduler_active", "scheduler_capacity", "work_pending", "work_leased"):
            point[key] = max(int(point[key]), int(row.get(key) or 0))
        for key in _COUNTER_KEYS:
            point[key] += _counter_delta(row, previous, key)
        previous = row
    return {"retention_sec": INGRESS_HISTORY_RETENTION_SEC, "bucket_sec": bucket, "points": list(points.values())}
