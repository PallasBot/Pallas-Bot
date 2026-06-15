"""帮助菜单：根据 metadata 中的 command_permission(s) 拼接当前生效权限文案。"""

from __future__ import annotations

from typing import Any

from .config import get_cmd_perm_config
from .registry import resolved_level

_LEVEL_CN: dict[str, str] = {
    "everyone": "所有人",
    "bot_moderator": "号主",
    "group_moderator": "群管/群主",
    "staff": "群管或号主",
    "superuser": "仅超管",
}


def _normalize_command_perm_ids(item: dict[str, Any]) -> list[str]:
    raw_list = item.get("command_permissions")
    if isinstance(raw_list, list):
        return [str(x).strip() for x in raw_list if str(x).strip()]
    one = item.get("command_permission")
    if one is not None and str(one).strip():
        return [str(one).strip()]
    return []


def raw_trigger_condition(item: dict[str, Any]) -> str:
    """metadata 中的触发条件原文。"""
    return str(item.get("trigger_condition", "未知") or "未知").strip() or "未知"


def effective_permission_avail_text(item: dict[str, Any]) -> str:
    """何人可用：单档为「{等级}可用」，多档为「任一：a / b 可用」。无 command_permission(s) 时返回空串。"""
    ids = _normalize_command_perm_ids(item)
    if not ids:
        return ""
    cfg = get_cmd_perm_config()
    ov = cfg.command_permission_overrides
    levels = [resolved_level(cid, ov) for cid in ids]
    labels = [_LEVEL_CN.get(lv, lv) for lv in levels]
    uniq: list[str] = []
    for lab in labels:
        if lab not in uniq:
            uniq.append(lab)
    if len(uniq) == 1:
        return f"{uniq[0]}可用"
    return f"任一：{' / '.join(uniq)}可用"


def trigger_condition_with_effective_perm(item: dict[str, Any]) -> str:
    """兼容旧名：等价于 `raw_trigger_condition`。"""
    return raw_trigger_condition(item)
