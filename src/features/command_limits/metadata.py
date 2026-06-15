"""从 PluginMetadata.extra 解析 command_limits 声明。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from nonebot.plugin import PluginMetadata


class CommandLimitDecl(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, description="与 command_permissions 相同的命令 ID")
    cd_sec: int = Field(ge=0, description="冷却秒数；0 表示关闭冷却")
    scope: Literal["group", "private", "auto"] = "auto"


def parse_command_limit_decl(raw: dict[str, Any]) -> CommandLimitDecl | None:
    try:
        item = dict(raw)
        if "cd_sec" not in item and "cd" in item:
            item["cd_sec"] = item.pop("cd")
        return CommandLimitDecl.model_validate(item)
    except (ValidationError, TypeError, ValueError):
        return None


def command_limits_from_metadata(meta: PluginMetadata | None) -> list[CommandLimitDecl]:
    if meta is None or not meta.extra:
        return []
    raw_list = meta.extra.get("command_limits")
    if not isinstance(raw_list, list):
        return []
    out: list[CommandLimitDecl] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        decl = parse_command_limit_decl(raw)
        if decl is not None:
            out.append(decl)
    return out


def command_limit_for_id(meta: PluginMetadata | None, command_id: str) -> CommandLimitDecl | None:
    cid = command_id.strip()
    for decl in command_limits_from_metadata(meta):
        if decl.id == cid:
            return decl
    return None
