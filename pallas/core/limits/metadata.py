"""从 PluginMetadata.extra / 插件元数据桩解析 command_limits 声明。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from nonebot.plugin import PluginMetadata


class CommandLimitDecl(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, description="与 command_permissions 相同的命令 ID")
    cd_sec: int = Field(ge=0, description="冷却秒数；0 表示关闭冷却")


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


def parse_command_limits_stub(init_path: Path) -> dict[str, Any] | None:
    """从插件 ``__init__.py`` 的 ``__plugin_meta__`` 字面量里提取名称与 command_limits。"""
    from pallas.core.commands.metadata_stub import parse_plugin_metadata_extra_stub

    stub = parse_plugin_metadata_extra_stub(init_path)
    if not stub:
        return None
    decls: list[CommandLimitDecl] = []
    for raw in stub.get("command_limits") or []:
        if not isinstance(raw, dict):
            continue
        decl = parse_command_limit_decl(raw)
        if decl is not None:
            decls.append(decl)
    plugin_name = str(stub.get("name") or "").strip()
    if not plugin_name and not decls:
        return None
    return {"name": plugin_name, "command_limits": decls}
