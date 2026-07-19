"""帮助菜单拼接命令权限文案。"""

from __future__ import annotations

from typing import Any

from .config import get_cmd_perm_config
from .registry import resolved_level

_LEVEL_CN: dict[str, str] = {
    "everyone": "所有人",
    "bot_moderator": "号主",
    "group_moderator": "群管/群主",
    "staff": "群管或号主",
    "superuser": "仅超管",
}


def _normalize_command_perm_ids(item: dict[str, Any]) -> list[str]:
    raw_list = item.get("command_permissions")
    if isinstance(raw_list, list):
        return [str(x).strip() for x in raw_list if str(x).strip()]
    one = item.get("command_permission")
    if one is not None and str(one).strip():
        return [str(one).strip()]
    return []


def command_ids_from_menu_item(item: dict[str, Any]) -> list[str]:
    """menu_data 条目绑定的命令 ID（command_permission / command_permissions）。"""
    return _normalize_command_perm_ids(item)


def trigger_conditions_by_command_id(menu_items: list[dict[str, Any]]) -> dict[str, list[str]]:
    """命令 ID -> 该命令在帮助菜单里声明的触发口令（去重保序）。"""
    out: dict[str, list[str]] = {}
    for item in menu_items:
        if not isinstance(item, dict):
            continue
        trigger = raw_trigger_condition(item)
        if not trigger or trigger == "未知":
            continue
        for cid in command_ids_from_menu_item(item):
            bucket = out.setdefault(cid, [])
            if trigger not in bucket:
                bucket.append(trigger)
    return out


def enrich_commands_with_menu_triggers(
    commands: list[dict[str, Any]],
    menu_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """为治理/能力面板命令补上 menu_data 里的实际触发口令。"""
    if not commands:
        return commands
    triggers_by_id = trigger_conditions_by_command_id(menu_items)
    if not triggers_by_id:
        return [dict(cmd) for cmd in commands]
    enriched: list[dict[str, Any]] = []
    for cmd in commands:
        if not isinstance(cmd, dict):
            continue
        row = dict(cmd)
        cid = str(row.get("command_id") or "").strip()
        triggers = triggers_by_id.get(cid) or []
        if triggers:
            row["trigger_condition"] = " / ".join(triggers)
        enriched.append(row)
    return enriched


def menu_data_for_loaded_plugin(plugin_name: str) -> list[dict[str, Any]]:
    """读取已加载插件 metadata.extra.menu_data。"""
    try:
        from nonebot import get_loaded_plugins

        from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package
    except ImportError:
        return []
    target = canonical_plugin_package((plugin_name or "").strip()) or (plugin_name or "").strip()
    if not target:
        return []
    for plugin in get_loaded_plugins():
        raw = str(getattr(plugin, "name", "") or "").strip()
        if not raw:
            continue
        if raw == plugin_name or canonical_plugin_package(raw) == target:
            meta = getattr(plugin, "metadata", None)
            extra = getattr(meta, "extra", None) or {}
            menu = extra.get("menu_data") if isinstance(extra, dict) else []
            if isinstance(menu, list):
                return [item for item in menu if isinstance(item, dict)]
    return []


def raw_trigger_condition(item: dict[str, Any]) -> str:
    """metadata 中的触发条件原文。"""
    return str(item.get("trigger_condition", "未知") or "未知").strip() or "未知"


def effective_permission_avail_text(item: dict[str, Any]) -> str:
    """拼接「何人可用」说明行。"""
    ids = _normalize_command_perm_ids(item)
    if not ids:
        return ""
    cfg = get_cmd_perm_config()
    ov = cfg.command_permission_overrides
    levels = [resolved_level(cid, ov) for cid in ids]
    labels = [_LEVEL_CN.get(lv, lv) for lv in levels]
    uniq: list[str] = []
    for lab in labels:
        if lab not in uniq:
            uniq.append(lab)
    if len(uniq) == 1:
        return f"{uniq[0]}可用"
    return f"任一：{' / '.join(uniq)}可用"


def trigger_condition_with_effective_perm(item: dict[str, Any]) -> str:
    """兼容旧接口，同 raw_trigger_condition。"""
    return raw_trigger_condition(item)
