"""插件治理 API 共用的插件行解析。"""

from __future__ import annotations

from typing import Any

from pallas.core.perm.menu_display import enrich_commands_with_menu_triggers
from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package


def canonical_plugin_name(name: str) -> str:
    return canonical_plugin_package((name or "").strip()) or (name or "").strip()


def find_capability_plugin_row(capabilities: dict[str, Any], target: str) -> dict[str, Any] | None:
    clean = canonical_plugin_name(target)
    for row in capabilities.get("plugins") or []:
        if not isinstance(row, dict):
            continue
        pname = str(row.get("plugin") or "")
        if not pname:
            continue
        if pname == target or pname == clean or canonical_plugin_name(pname) == clean:
            return row
    return None


def find_catalog_plugin_row(rows: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    clean = canonical_plugin_name(target)
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        resolved = str(row.get("resolved_plugin_id") or name)
        candidates = {name, resolved, str(row.get("nb_plugin_name") or "")}
        if clean in candidates or target in candidates:
            return row
        if any(canonical_plugin_name(item) == clean for item in candidates if item):
            return row
    return None


def governance_row_from_catalog(target: str, catalog_row: dict[str, Any]) -> dict[str, Any]:
    clean = canonical_plugin_name(target)
    metadata = catalog_row.get("metadata") if isinstance(catalog_row.get("metadata"), dict) else {}
    title = str(metadata.get("name") or catalog_row.get("name") or clean).strip() or clean
    return {
        "plugin": clean,
        "title": title,
        "commands": [],
        "llm_tools": [],
        "knowledge_sources": [],
        "storage_keys": [],
        "reload_policy": None,
        "activation_policy": None,
    }


__all__ = [
    "canonical_plugin_name",
    "enrich_commands_with_menu_triggers",
    "find_capability_plugin_row",
    "find_catalog_plugin_row",
    "governance_row_from_catalog",
]
