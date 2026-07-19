"""从 PluginMetadata.extra / 插件元数据桩解析 command_permissions 声明。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .registry import VALID_LEVELS

if TYPE_CHECKING:
    from pathlib import Path

    from nonebot.plugin import PluginMetadata


class CommandPermissionDecl(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    default: str = Field(min_length=1)


def parse_command_permission_decl(raw: dict[str, Any]) -> CommandPermissionDecl | None:
    try:
        item = dict(raw)
        if "id" not in item and "command_id" in item:
            item["id"] = item.pop("command_id")
        if "label" not in item and "name" in item:
            item["label"] = item.pop("name")
        if "default" not in item and "default_level" in item:
            item["default"] = item.pop("default_level")
        item["default"] = str(item.get("default") or "everyone").strip().lower()
        if item["default"] not in VALID_LEVELS:
            item["default"] = "everyone"
        return CommandPermissionDecl.model_validate(item)
    except (ValidationError, TypeError, ValueError):
        return None


def command_permissions_from_metadata(meta: PluginMetadata | None) -> list[CommandPermissionDecl]:
    if meta is None or not meta.extra:
        return []
    raw_list = meta.extra.get("command_permissions")
    if not isinstance(raw_list, list):
        return []
    out: list[CommandPermissionDecl] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        decl = parse_command_permission_decl(raw)
        if decl is not None:
            out.append(decl)
    return out


def parse_command_permissions_stub(init_path: Path) -> dict[str, Any] | None:
    """从插件 ``__init__.py`` 的 ``__plugin_meta__`` 字面量里提取名称与 command_permissions。"""
    from pallas.core.commands.metadata_stub import parse_plugin_metadata_extra_stub

    stub = parse_plugin_metadata_extra_stub(init_path)
    if not stub:
        return None
    decls: list[CommandPermissionDecl] = []
    for raw in stub.get("command_permissions") or []:
        if not isinstance(raw, dict):
            continue
        decl = parse_command_permission_decl(raw)
        if decl is not None:
            decls.append(decl)
    plugin_name = str(stub.get("name") or "").strip()
    if not plugin_name and not decls:
        return None
    return {"name": plugin_name, "command_permissions": decls}
