"""接话行为：由 bot 账号派生与群学习统计推导，无手动人设口令。"""

from .compile_group_style import (
    build_group_style_hints,
    compile_group_style_prompt,
    compile_group_style_snapshot,
)
from .cross_group_profiler import build_bot_cross_group_persona, group_style_weight
from .cross_group_refresh import (
    clear_bot_cross_group_dirty_state,
    mark_bot_cross_group_dirty,
    pop_dirty_bot_cross_group_batch,
    refresh_bot_cross_group_persona,
    refresh_dirty_bot_cross_group_batch,
)
from .group_profiler import build_group_style_profile
from .group_style_refresh import (
    bind_group_style_refresh_lifecycle,
    clear_group_style_dirty_state,
    mark_group_style_dirty,
    pop_dirty_group_style_batch,
    refresh_dirty_group_style_batch,
)
from .loader import invalidate_persona_cache, resolve_persona
from .model import ResolvedPersona

__all__ = [
    "ResolvedPersona",
    "bind_group_style_refresh_lifecycle",
    "build_bot_cross_group_persona",
    "build_group_style_hints",
    "build_group_style_profile",
    "clear_bot_cross_group_dirty_state",
    "clear_group_style_dirty_state",
    "compile_group_style_prompt",
    "compile_group_style_snapshot",
    "group_style_weight",
    "invalidate_persona_cache",
    "mark_bot_cross_group_dirty",
    "mark_group_style_dirty",
    "pop_dirty_bot_cross_group_batch",
    "pop_dirty_group_style_batch",
    "refresh_bot_cross_group_persona",
    "refresh_dirty_bot_cross_group_batch",
    "refresh_dirty_group_style_batch",
    "resolve_persona",
]
