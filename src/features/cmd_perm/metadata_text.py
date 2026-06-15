"""PluginMetadata 用户向文案格式。"""

from __future__ import annotations

# trigger_scene 允许值
SCENE_GROUP = "群内"
SCENE_PRIVATE = "私聊"
SCENE_BOTH = "群内或私聊"
SCENE_AUTO = "自动"


def usage_line(trigger: str, description: str) -> str:
    """一行用法：口令 — 说明。"""
    return f"{trigger} — {description}"


def join_usage(*lines: str, numbered: bool | None = None) -> str:
    """拼接 usage 正文。默认：2 条及以上自动加 1. 2. 3."""
    items = [line.strip() for line in lines if line.strip()]
    if not items:
        return ""
    use_numbers = numbered if numbered is not None else len(items) >= 2
    if not use_numbers:
        return "\n".join(items)
    return "\n".join(f"{i}. {line}" for i, line in enumerate(items, 1))
