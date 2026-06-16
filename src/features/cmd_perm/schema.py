"""从 PluginMetadata.extra['command_permissions'] 合并默认等级，并生成 WebUI 矩阵数据。"""

from __future__ import annotations

from operator import itemgetter
from typing import Any

from nonebot import get_loaded_plugins

from .registry import DEFAULT_COMMAND_PERMISSIONS, VALID_LEVELS, canonical_command_id

_merged_defaults_cache: dict[str, str] | None = None

# WebUI 单选列
UI_LEVELS: tuple[tuple[str, str], ...] = (
    ("everyone", "所有人"),
    ("bot_moderator", "号主"),
    ("group_moderator", "群管/群主"),
    ("staff", "群管或号主"),
    ("superuser", "仅超管"),
)


def clear_merged_defaults_cache() -> None:
    global _merged_defaults_cache
    _merged_defaults_cache = None


def _parse_command_permission_rows(raw: Any) -> list[dict[str, str]]:
    if not raw or not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or item.get("command_id") or "").strip()
        if not cid:
            continue
        label = str(item.get("label") or item.get("name") or cid).strip()
        default = str(item.get("default") or item.get("default_level") or "everyone").strip().lower()
        if default not in VALID_LEVELS:
            default = "everyone"
        out.append({"id": cid, "label": label, "default": default})
    return out


def merged_default_levels() -> dict[str, str]:
    """命令 ID -> 默认等级。"""
    global _merged_defaults_cache
    if _merged_defaults_cache is not None:
        return _merged_defaults_cache
    m = {str(k): str(v) for k, v in DEFAULT_COMMAND_PERMISSIONS.items()}
    for p in get_loaded_plugins():
        if not p.name:
            continue
        meta = getattr(p, "metadata", None)
        extra = (getattr(meta, "extra", None) or {}) if meta else {}
        for row in _parse_command_permission_rows(extra.get("command_permissions")):
            m[row["id"]] = row["default"]
    _merged_defaults_cache = m
    return _merged_defaults_cache


def default_level_for(command_id: str) -> str:
    cid = canonical_command_id((command_id or "").strip())
    return merged_default_levels().get(cid, "everyone")


def build_command_perm_ui(overrides: dict[str, str]) -> dict[str, Any]:
    """供 WebUI 渲染：按插件分组 + 每命令当前生效等级。"""
    defaults = merged_default_levels()
    meta_rows: dict[str, tuple[str, str, str]] = {}
    for p in get_loaded_plugins():
        if not p.name:
            continue
        meta = getattr(p, "metadata", None)
        title = (getattr(meta, "name", None) or p.name or "").strip() or p.name
        extra = (getattr(meta, "extra", None) or {}) if meta else {}
        for row in _parse_command_permission_rows(extra.get("command_permissions")):
            cid = row["id"]
            meta_rows[cid] = (p.name, title, row["label"])

    groups: dict[str, dict[str, Any]] = {}
    for cid, default in sorted(defaults.items(), key=itemgetter(0)):
        raw_o = (overrides.get(cid) or "").strip().lower()
        if raw_o in VALID_LEVELS:
            effective = raw_o
        else:
            effective = default
        if cid in meta_rows:
            pname, ptitle, label = meta_rows[cid]
        else:
            from .ui_labels import command_label_for_id, plugin_name_for_command_id, plugin_title_for_name

            pname = plugin_name_for_command_id(cid)
            ptitle = plugin_title_for_name(pname)
            label = command_label_for_id(cid)
        g = groups.setdefault(pname, {"plugin": pname, "title": ptitle, "commands": []})
        if cid in meta_rows and g["title"] == g["plugin"]:
            g["title"] = ptitle
        g["commands"].append({
            "command_id": cid,
            "label": label,
            "default_level": default,
            "effective_level": effective,
        })
    for g in groups.values():
        g["commands"].sort(key=itemgetter("label", "command_id"))
    plugins_out = sorted(groups.values(), key=itemgetter("plugin"))
    return {
        "levels": [{"id": lid, "label": lab} for lid, lab in UI_LEVELS],
        "plugins": plugins_out,
    }
