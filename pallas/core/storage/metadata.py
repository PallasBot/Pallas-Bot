"""从 PluginMetadata.extra['plugin_storage'] 解析声明。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from nonebot.plugin import PluginMetadata

StorageScope = Literal["group", "user", "bot", "deploy"]


class PluginStorageDecl(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1)
    scope: StorageScope = "group"
    label: str = ""
    ephemeral: bool = False


def parse_plugin_storage_decl(raw: dict[str, Any]) -> PluginStorageDecl | None:
    try:
        return PluginStorageDecl.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        return None


def plugin_storage_from_metadata(meta: PluginMetadata | None) -> list[PluginStorageDecl]:
    if meta is None or not meta.extra:
        return []
    raw_list = meta.extra.get("plugin_storage")
    if not isinstance(raw_list, list):
        return []
    out: list[PluginStorageDecl] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        decl = parse_plugin_storage_decl(raw)
        if decl is not None:
            out.append(decl)
    return out


def iter_loaded_plugin_storage() -> list[tuple[str, str, PluginStorageDecl]]:
    from nonebot import get_loaded_plugins

    rows: list[tuple[str, str, PluginStorageDecl]] = []
    for plugin in get_loaded_plugins():
        if not plugin.name:
            continue
        meta = getattr(plugin, "metadata", None)
        title = (getattr(meta, "name", None) or plugin.name or "").strip() or plugin.name
        for decl in plugin_storage_from_metadata(meta):
            rows.append((plugin.name, title, decl))  # noqa: PERF401
    return rows
