"""命令权限运行时元数据。"""

from __future__ import annotations

from nonebot.permission import Permission  # noqa: TC002

_COMMAND_PERMISSION_META: dict[int, tuple[str, str]] = {}


def mark_command_permission_meta(permission: Permission, *, command_id: str, scene: str) -> Permission:
    _COMMAND_PERMISSION_META[id(permission)] = (str(command_id).strip(), str(scene).strip())
    return permission


def get_command_permission_meta(permission: Permission | None) -> tuple[str, str] | None:
    if permission is None:
        return None
    return _COMMAND_PERMISSION_META.get(id(permission))
