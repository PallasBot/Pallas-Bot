"""在 ``PluginMetadata.extra`` 中声明可配置命令权限的辅助函数。"""

from __future__ import annotations

from typing import Literal

from .registry import VALID_LEVELS

PermissionLevel = Literal["superuser", "group_moderator", "bot_moderator", "staff", "everyone"]


def command_perm_row(
    command_id: str,
    label: str,
    default: PermissionLevel = "everyone",
) -> dict[str, str]:
    """单条 ``extra['command_permissions']`` 项。"""
    cid = (command_id or "").strip()
    if not cid:
        raise ValueError("command_id 不能为空")
    level = (default or "everyone").strip().lower()
    if level not in VALID_LEVELS:
        level = "everyone"
    return {
        "id": cid,
        "label": (label or cid).strip() or cid,
        "default": level,
    }


def command_perm_list(*rows: dict[str, str]) -> list[dict[str, str]]:
    """组装 ``PluginMetadata(..., extra={'command_permissions': command_perm_list(...)})``。"""
    return list(rows)
