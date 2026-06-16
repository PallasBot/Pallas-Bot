"""PluginMetadata.extra 声明辅助，与 cmd_perm 对称。"""

from __future__ import annotations


def command_limit_row(command_id: str, cd_sec: int) -> dict[str, str | int]:
    cid = (command_id or "").strip()
    if not cid:
        raise ValueError("command_id 不能为空")
    return {"id": cid, "cd_sec": max(0, int(cd_sec))}


def command_limit_list(*rows: dict[str, str | int]) -> list[dict[str, str | int]]:
    return list(rows)
