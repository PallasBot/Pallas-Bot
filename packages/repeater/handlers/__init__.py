"""注册 repeater matcher 与调度任务。"""

from .. import (
    emoji_reaction,  # noqa: F401
    startup,  # noqa: F401
)
from ..config import get_repeater_config, sync_repeater_runtime_constants
from . import ban, lifecycle, message, scheduler

sync_repeater_runtime_constants(get_repeater_config())

__all__ = ["ban", "emoji_reaction", "lifecycle", "message", "scheduler"]
