"""媒体类 AI 任务 callback 收尾 hook（按 task_type 注册）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MediaTaskFailureHook = Callable[[dict[str, Any]], None]
MediaTaskSuccessHook = Callable[[dict[str, Any], bytes, int], None]

_hooks: dict[str, tuple[MediaTaskFailureHook | None, MediaTaskSuccessHook | None]] = {}


def register_media_task_hooks(
    task_type: str,
    *,
    on_failure: MediaTaskFailureHook | None = None,
    on_success: MediaTaskSuccessHook | None = None,
) -> None:
    key = (task_type or "").strip()
    if not key:
        raise ValueError("task_type must be non-empty")
    _hooks[key] = (on_failure, on_success)


def invoke_media_task_failure(task: dict[str, Any]) -> bool:
    key = str(task.get("task_type") or "").strip()
    hook = _hooks.get(key, (None, None))[0]
    if hook is None:
        return False
    hook(task)
    return True


def invoke_media_task_success(task: dict[str, Any], *, image_bytes: bytes, group_id: int) -> bool:
    key = str(task.get("task_type") or "").strip()
    hook = _hooks.get(key, (None, None))[1]
    if hook is None:
        return False
    hook(task, image_bytes, group_id)
    return True


def clear_media_task_hooks_for_tests() -> None:
    _hooks.clear()
