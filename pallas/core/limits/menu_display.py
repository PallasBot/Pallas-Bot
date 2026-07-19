"""帮助菜单拼接命令冷却文案。"""

from __future__ import annotations

from typing import Any

from pallas.core.perm.menu_display import command_ids_from_menu_item

from .config import get_command_limits_config
from .schema import effective_command_limit_for


def effective_command_cooldown_text(item: dict[str, Any]) -> str:
    """menu_data 条目绑定的命令 ID 对应生效冷却；无绑定或未声明时返回空串。"""
    ids = command_ids_from_menu_item(item)
    if not ids:
        return ""
    overrides = get_command_limits_config().command_limit_overrides
    cds: list[int] = []
    for cid in ids:
        cd = effective_command_limit_for(cid, overrides)
        if cd is not None:
            cds.append(cd)
    if not cds:
        return ""
    uniq: list[int] = []
    for cd in cds:
        if cd not in uniq:
            uniq.append(cd)
    if len(uniq) == 1:
        cd = uniq[0]
        if cd <= 0:
            return "无冷却"
        return f"冷却 {cd} 秒"
    parts = ["无" if cd <= 0 else f"{cd}秒" for cd in uniq]
    return f"冷却 {' / '.join(parts)}"
