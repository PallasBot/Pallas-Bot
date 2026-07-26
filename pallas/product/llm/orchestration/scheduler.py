from __future__ import annotations

import time

from .task_store import create_task, list_tasks, update_task_status


def register_once(
    name: str, *, run_at: int, payload: dict | None = None, group_id: int | None = None, user_id: int | None = None
):
    return create_task(name, payload, group_id=group_id, user_id=user_id, run_at=run_at)


def register_interval(
    name: str,
    *,
    interval_sec: int,
    payload: dict | None = None,
    group_id: int | None = None,
    user_id: int | None = None,
):
    return create_task(
        name,
        payload,
        group_id=group_id,
        user_id=user_id,
        run_at=int(time.time()) + max(1, interval_sec),
        interval_sec=interval_sec,
    )


def list_due_tasks(now: int | None = None):
    current = int(now or time.time())
    return [task for task in list_tasks(status="pending") if task.run_at is None or task.run_at <= current]


def mark_task_done(task_id: str):
    return update_task_status(task_id, "done")


def poll_due_tasks():
    return list_due_tasks()
