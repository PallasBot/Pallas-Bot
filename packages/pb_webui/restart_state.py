"""主节点进程重启窗口状态（供 /health 与 WebUI 进度探测）。"""

from __future__ import annotations

import time
import uuid

_BOOT_ID = uuid.uuid4().hex[:12]
_restart_requested_at: float | None = None
_restart_workers_only: bool = False
_RESTART_FLAG_TTL_SEC = 180.0


def get_boot_id() -> str:
    return _BOOT_ID


def mark_restart_requested(*, workers_only: bool = False) -> None:
    global _restart_requested_at, _restart_workers_only
    _restart_requested_at = time.time()
    _restart_workers_only = workers_only


def clear_restart_requested() -> None:
    global _restart_requested_at, _restart_workers_only
    _restart_requested_at = None
    _restart_workers_only = False


def restart_runtime_fields() -> dict[str, object]:
    global _restart_requested_at, _restart_workers_only
    restarting = False
    workers_only = False
    if _restart_requested_at is not None:
        age = time.time() - _restart_requested_at
        if age <= _RESTART_FLAG_TTL_SEC:
            restarting = True
            workers_only = _restart_workers_only
        else:
            _restart_requested_at = None
            _restart_workers_only = False
    fields: dict[str, object] = {
        "boot_id": _BOOT_ID,
        "restarting": restarting,
    }
    if workers_only:
        fields["restart_workers_only"] = True
    if restarting:
        fields["ok"] = False
    return fields
