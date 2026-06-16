"""在 PluginMetadata.extra 中声明插件存储键。"""

from __future__ import annotations

from typing import Literal

StorageScope = Literal["group", "user", "bot", "deploy"]


def plugin_storage_row(
    key: str,
    *,
    scope: StorageScope = "group",
    label: str = "",
    ephemeral: bool = False,
) -> dict[str, str | bool]:
    storage_key = (key or "").strip()
    if not storage_key:
        raise ValueError("storage key 不能为空")
    scope_name = (scope or "group").strip().lower()
    if scope_name not in ("group", "user", "bot", "deploy"):
        scope_name = "group"
    return {
        "key": storage_key,
        "scope": scope_name,
        "label": (label or storage_key).strip(),
        "ephemeral": bool(ephemeral),
    }


def plugin_storage_list(*rows: dict[str, str | bool]) -> list[dict[str, str | bool]]:
    return list(rows)
