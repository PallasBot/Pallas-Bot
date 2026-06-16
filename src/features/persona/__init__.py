"""接话行为：由 bot 账号派生与群学习统计推导，无手动人设口令。"""

from .compile_group_style import (
    build_group_style_hints,
    compile_group_style_prompt,
    compile_group_style_snapshot,
)
from .compile_persona_prompt import (
    PersonaPromptBundle,
    PersonaPromptMetadata,
    PersonaPromptSections,
    assemble_persona_system,
    build_bot_behavior_prompt,
    clear_base_system_prompt_cache,
    compile_persona_prompt,
    compile_persona_prompt_for,
    load_base_system_prompt,
    resolve_base_system_prompt_path,
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
from .loader import invalidate_persona_cache, resolve_persona, resolve_persona_for_message
from .model import ResolvedPersona

__all__ = [
    "PersonaPromptBundle",
    "PersonaPromptMetadata",
    "PersonaPromptSections",
    "ResolvedPersona",
    "assemble_persona_system",
    "bind_group_style_refresh_lifecycle",
    "build_bot_behavior_prompt",
    "build_bot_cross_group_persona",
    "build_group_style_hints",
    "build_group_style_profile",
    "clear_base_system_prompt_cache",
    "clear_bot_cross_group_dirty_state",
    "clear_group_style_dirty_state",
    "compile_group_style_prompt",
    "compile_group_style_snapshot",
    "compile_persona_prompt",
    "compile_persona_prompt_for",
    "group_style_weight",
    "invalidate_persona_cache",
    "load_base_system_prompt",
    "mark_bot_cross_group_dirty",
    "mark_group_style_dirty",
    "pop_dirty_bot_cross_group_batch",
    "pop_dirty_group_style_batch",
    "refresh_bot_cross_group_persona",
    "refresh_dirty_bot_cross_group_batch",
    "refresh_dirty_group_style_batch",
    "resolve_base_system_prompt_path",
    "resolve_persona",
    "resolve_persona_for_message",
]
