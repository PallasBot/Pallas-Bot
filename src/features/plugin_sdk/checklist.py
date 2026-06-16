"""插件元数据最小自检（开发/测试用）。"""

from __future__ import annotations

from typing import Any


def missing_command_declarations(
    extra: dict[str, Any] | None,
    *,
    command_ids: set[str] | frozenset[str],
) -> list[str]:
    if not command_ids:
        return []
    extra = extra or {}
    perm_ids = {
        str(row.get("id") or "").strip() for row in extra.get("command_permissions") or [] if isinstance(row, dict)
    }
    limit_ids = {str(row.get("id") or "").strip() for row in extra.get("command_limits") or [] if isinstance(row, dict)}
    missing: list[str] = []
    for cid in sorted(command_ids):
        if cid not in perm_ids:
            missing.append(f"{cid}: command_permissions")
        if cid not in limit_ids:
            missing.append(f"{cid}: command_limits")
    return missing
