"""注册 repeater matcher 与调度任务。"""

from .. import startup  # noqa: F401
from . import ban, lifecycle, message, scheduler

__all__ = ["ban", "lifecycle", "message", "scheduler"]
