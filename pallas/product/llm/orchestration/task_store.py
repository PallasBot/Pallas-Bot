from __future__ import annotations

import json
import time
import uuid
from pathlib import Path  # noqa: TC003
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir

from .models import TaskRecord


def _path() -> Path:
    path = plugin_data_dir("pb_webui", create=True) / "pallas_llm" / "tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> list[TaskRecord]:
    try:
        return [TaskRecord.model_validate(item) for item in json.loads(_path().read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return []


def _save(rows: list[TaskRecord]) -> None:
    _path().write_text(
        json.dumps([item.model_dump(mode="json") for item in rows], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def create_task(
    name: str,
    payload: dict[str, Any] | None = None,
    *,
    group_id: int | None = None,
    user_id: int | None = None,
    run_at: int | None = None,
    interval_sec: int = 0,
) -> TaskRecord:
    task = TaskRecord(
        task_id=f"task-{uuid.uuid4().hex[:12]}",
        name=name,
        payload=payload or {},
        group_id=group_id,
        user_id=user_id,
        run_at=run_at,
        interval_sec=max(0, interval_sec),
    )
    rows = _load()
    rows.append(task)
    _save(rows)
    return task


def list_tasks(*, status: str | None = None) -> list[TaskRecord]:
    return [task for task in _load() if status is None or task.status == status]


def get_task(task_id: str) -> TaskRecord | None:
    return next((task for task in _load() if task.task_id == task_id), None)


def update_task_status(task_id: str, status: str) -> TaskRecord | None:
    rows = _load()
    for index, task in enumerate(rows):
        if task.task_id == task_id:
            updated = task.model_copy(update={"status": status, "updated_at": int(time.time())})
            rows[index] = updated
            _save(rows)
            return updated
    return None


def cancel_task(task_id: str) -> TaskRecord | None:
    return update_task_status(task_id, "cancelled")
