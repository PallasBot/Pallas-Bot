"""work aux 跨进程运行状态。"""

from __future__ import annotations

import json
import time
from typing import Any

from pallas.core.foundation.paths import DATA_ROOT

WORK_AUX_STATUS_PATH = DATA_ROOT / "pallas_work" / "run" / "status.json"


def write_work_aux_status(*, consumers: int, stats: dict[str, float | int | None]) -> None:
    payload = {"updated_at": time.time(), "consumers": max(0, int(consumers)), **stats}
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
    }
