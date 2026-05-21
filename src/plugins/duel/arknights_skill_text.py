"""兼容 re-export；新代码请 `from src.common.arknights.skill_text import ...`。"""

from src.common.arknights.skill_text import (
    blackboard_list_to_dict,
    format_blackboard_value,
    render_skill_level_plain,
    skill_last_level_plain,
    strip_ark_rich_tags,
    substitute_skill_placeholders,
)

__all__ = [
    "blackboard_list_to_dict",
    "format_blackboard_value",
    "render_skill_level_plain",
    "skill_last_level_plain",
    "strip_ark_rich_tags",
    "substitute_skill_placeholders",
]
