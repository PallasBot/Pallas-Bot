"""work aux 跨进程运行状态。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from pallas.core.foundation.paths import DATA_ROOT

WORK_AUX_STATUS_PATH = DATA_ROOT / "pallas_work" / "run" / "status.json"


@dataclass(slots=True)
class WorkAuxRuntimeMetrics:
    completed_since_start: int = 0
    failed_since_start: int = 0
    retried_since_start: int = 0
    dead_lettered_since_start: int = 0

    def record_completed(self, count: int = 1) -> None:
        self.completed_since_start += max(0, int(count))

    def record_failed(self) -> None:
        self.failed_since_start += 1

    def record_retried(self) -> None:
        self.retried_since_start += 1

    def record_dead_lettered(self) -> None:
        self.dead_lettered_since_start += 1

    def snapshot(self) -> dict[str, int]:
        return {
            "completed_since_start": self.completed_since_start,
            "failed_since_start": self.failed_since_start,
            "retried_since_start": self.retried_since_start,
            "dead_lettered_since_start": self.dead_lettered_since_start,
        }


def write_work_aux_status(
    *,
    consumers: int,
    stats: dict[str, float | int | None],
    runtime_metrics: dict[str, int] | None = None,
) -> None:
    payload = {
        "updated_at": time.time(),
        "consumers": max(0, int(consumers)),
        **stats,
        **(runtime_metrics or {}),
    }
    path = WORK_AUX_STATUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def work_aux_status() -> dict[str, Any]:
    try:
        raw = json.loads(WORK_AUX_STATUS_PATH.read_text(encoding="utf-8"))
        updated_at = float(raw["updated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return {"available": False}
    age = max(0.0, time.time() - updated_at)
    return {
        "available": True,
        "heartbeat_age_sec": round(age, 2),
        "consumers": int(raw.get("consumers") or 0),
        "pending": int(raw.get("pending") or 0),
        "leased": int(raw.get("leased") or 0),
        "dead_lettered": int(raw.get("dead_lettered") or 0),
        "oldest_pending_age_sec": raw.get("oldest_pending_age_sec"),
        "max_attempts": int(raw.get("max_attempts") or 0),
        "completed_since_start": int(raw.get("completed_since_start") or 0),
        "failed_since_start": int(raw.get("failed_since_start") or 0),
        "retried_since_start": int(raw.get("retried_since_start") or 0),
        "dead_lettered_since_start": int(raw.get("dead_lettered_since_start") or 0),
    }
