"""从 PluginMetadata.extra['command_limits'] 聚合默认命令冷却，并生成 WebUI 数据。"""

from __future__ import annotations

from operator import itemgetter
from typing import Any

from nonebot import get_loaded_plugins

from src.console.webui.plugin_catalog import discover_extra_plugin_packages, discover_plugin_packages
from src.foundation.paths import PROJECT_ROOT

from .metadata import command_limits_from_metadata, parse_command_limits_stub

_merged_defaults_cache: dict[str, int] | None = None


def _loaded_plugin_rows() -> list[tuple[str, str, list[Any]]]:
    rows: list[tuple[str, str, list[Any]]] = []
    for plugin in get_loaded_plugins():
        if not plugin.name:
            continue
        meta = getattr(plugin, "metadata", None)
        title = (getattr(meta, "name", None) or plugin.name or "").strip() or plugin.name
        decls = command_limits_from_metadata(meta)
        if decls:
            rows.append((plugin.name, title, decls))
    return rows


def _disk_plugin_rows() -> list[tuple[str, str, list[Any]]]:
    loaded_names = {name for name, _title, _decls in _loaded_plugin_rows()}
    extra_pkgs = discover_extra_plugin_packages()
    roots = [(package, PROJECT_ROOT / "src" / "plugins" / package) for package in discover_plugin_packages()]
    roots.extend(extra_pkgs.items())

    rows: list[tuple[str, str, list[Any]]] = []
    seen: set[str] = set()
    for package, root in roots:
        if package in loaded_names or package in seen:
            continue
        init_path = root / "__init__.py"
        if not init_path.is_file():
            continue
        stub = parse_command_limits_stub(init_path)
        if not stub:
            continue
        decls = stub.get("command_limits") or []
        if not decls:
            continue
        title = str(stub.get("name") or package).strip() or package
        rows.append((package, title, decls))
        seen.add(package)
    return rows


def _all_command_limit_rows() -> list[tuple[str, str, list[Any]]]:
    loaded = _loaded_plugin_rows()
    disk = _disk_plugin_rows()
    return loaded + disk


def clear_merged_command_limits_cache() -> None:
    global _merged_defaults_cache
    _merged_defaults_cache = None


def merged_default_command_limits() -> dict[str, int]:
    global _merged_defaults_cache
    if _merged_defaults_cache is not None:
        return _merged_defaults_cache
    merged: dict[str, int] = {}
    for _plugin_name, _title, decls in _all_command_limit_rows():
        for row in decls:
            merged[row.id] = row.cd_sec
    _merged_defaults_cache = merged
    return _merged_defaults_cache


def effective_command_limit_for(command_id: str, overrides: dict[str, int] | None = None) -> int | None:
    cid = (command_id or "").strip()
    if not cid:
        return None
    override_map = overrides or {}
    if cid in override_map:
        return override_map[cid]
    return merged_default_command_limits().get(cid)


def build_command_limits_ui(overrides: dict[str, int]) -> dict[str, Any]:
    defaults = merged_default_command_limits()
    meta_rows: dict[str, tuple[str, str, str]] = {}
    for plugin_name, title, decls in _all_command_limit_rows():
        for row in decls:
            meta_rows[row.id] = (plugin_name, title, row.id)

    groups: dict[str, dict[str, Any]] = {}
    for cid, default_cd in sorted(defaults.items(), key=itemgetter(0)):
        effective_cd = overrides.get(cid, default_cd)
        if cid in meta_rows:
            pname, ptitle, label = meta_rows[cid]
        else:
            from src.features.cmd_perm.ui_labels import (
                command_label_for_id,
                plugin_name_for_command_id,
                plugin_title_for_name,
            )

            pname = plugin_name_for_command_id(cid)
            ptitle = plugin_title_for_name(pname)
            label = command_label_for_id(cid)
        group = groups.setdefault(pname, {"plugin": pname, "title": ptitle, "commands": []})
        group["commands"].append({
            "command_id": cid,
            "label": label,
            "default_cd_sec": default_cd,
            "effective_cd_sec": effective_cd,
        })
    for group in groups.values():
        group["commands"].sort(key=itemgetter("label", "command_id"))
    plugins_out = sorted(groups.values(), key=itemgetter("plugin"))
    commands_out = [
        {
            "id": row["command_id"],
            "label": row["label"],
            "default_cd_sec": row["default_cd_sec"],
            "effective_cd_sec": row["effective_cd_sec"],
            "plugin": group["plugin"],
            "title": group["title"],
        }
        for group in plugins_out
        for row in group["commands"]
    ]
    return {"plugins": plugins_out, "commands": commands_out}
