"""二级/三级帮助页结构化数据。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pallas.core.limits import effective_command_cooldown_text
from pallas.core.perm import (
    effective_permission_avail_text,
    help_say_phrase,
    help_scene_text,
    iter_plugin_detail_menu,
)

from .markdown_generator import HelpMarkdownIssue
from .plugin_manager import find_plugin, plugin_display_name
from .plugin_match import normalize_help_key

_NUMBERED_USAGE_RE = re.compile(r"^\d+\.\s*")
# trigger_condition 里的口令分隔符（多个等价口令以 / 、| 分隔）
_CMD_ALT_SPLIT_RE = re.compile(r"[/、|]+")
# 含占位符的条目（如「同意好友 <QQ号>」「牛牛救一下 [@用户]」「牛牛帮助 〈插件名〉」）不作直达口令
_CMD_PLACEHOLDER_RE = re.compile(r"[<>\[\]〈〉]")


def normalize_plugin_usage_text(usage: str) -> str:
    """插件 usage 统一为 join_usage 序号列表（≥2 条时 1. 2. 3.）。"""
    from pallas.core.perm.metadata_text import join_usage

    raw = (usage or "").strip()
    if not raw:
        return "暂无说明"
    if " · " in raw and "\n" not in raw:
        parts = [part.strip() for part in raw.split(" · ") if part.strip()]
    else:
        parts = [line.strip() for line in raw.splitlines() if line.strip()]
    items = [_NUMBERED_USAGE_RE.sub("", part) for part in parts if part]
    if len(items) >= 2:
        return join_usage(*items)
    return items[0] if items else "暂无说明"


@dataclass(frozen=True, slots=True)
class HelpFunctionRow:
    index: int
    func: str
    say: str
    scene: str
    perm: str
    cooldown: str
    brief: str
    detail: str


@dataclass(slots=True)
class PluginDetailData:
    plugin: Any
    display_name: str
    description: str
    usage: str
    enabled: bool | None
    functions: list[HelpFunctionRow] = field(default_factory=list)
    extra_sections: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FunctionDetailData:
    plugin: Any
    display_name: str
    func_name: str
    index: int
    total: int
    say: str
    scene: str
    perm: str
    cooldown: str
    brief: str
    detail: str
    extra_sections: list[tuple[str, str]] = field(default_factory=list)


def build_plugin_detail_data(
    plugin_name: str,
    *,
    plugin_enabled: bool | None,
) -> tuple[PluginDetailData | None, HelpMarkdownIssue]:
    target_plugin = find_plugin(plugin_name)
    if not target_plugin:
        return None, HelpMarkdownIssue.PLUGIN_NOT_FOUND

    display_name = plugin_display_name(target_plugin)
    data = PluginDetailData(
        plugin=target_plugin,
        display_name=display_name,
        description="暂无描述",
        usage="暂无说明",
        enabled=plugin_enabled,
    )

    meta = getattr(target_plugin, "metadata", None)
    if meta is not None:
        data.description = str(getattr(meta, "description", None) or "暂无描述").strip()
        data.usage = normalize_plugin_usage_text(str(getattr(meta, "usage", None) or "暂无说明"))
        menu_data = []
        if getattr(meta, "extra", None):
            menu_data = list(iter_plugin_detail_menu(target_plugin, meta.extra.get("menu_data", [])))
        for i, item in enumerate(menu_data, 1):
            perm_raw = effective_permission_avail_text(item)
            cd_raw = effective_command_cooldown_text(item)
            data.functions.append(
                HelpFunctionRow(
                    index=i,
                    func=str(item.get("func", f"未命名功能 {i}") or f"未命名功能 {i}"),
                    say=help_say_phrase(item),
                    scene=help_scene_text(item),
                    perm=perm_raw or "—",
                    cooldown=cd_raw or "—",
                    brief=str(item.get("brief_des", "") or "").strip(),
                    detail=str(item.get("detail_des", "") or "").strip(),
                )
            )

    if target_plugin.name == "maa":
        from pallas.core.plugin_coord import maa as maa_coord

        data.extra_sections.append(("MAA 对接地址", maa_coord.format_maa_http_setup_help()))

    return data, HelpMarkdownIssue.OK


def build_function_detail_data(
    plugin_name: str,
    function_name: str,
) -> tuple[FunctionDetailData | None, HelpMarkdownIssue]:
    target_plugin = find_plugin(plugin_name)
    if not target_plugin:
        return None, HelpMarkdownIssue.PLUGIN_NOT_FOUND

    meta = getattr(target_plugin, "metadata", None)
    if meta is None or not getattr(meta, "extra", None):
        return None, HelpMarkdownIssue.METADATA_MISSING

    user_menu = list(iter_plugin_detail_menu(target_plugin, meta.extra.get("menu_data", [])))
    target_function = None
    target_index = -1

    if function_name.isdigit():
        index = int(function_name) - 1
        if 0 <= index < len(user_menu):
            target_function = user_menu[index]
            target_index = index + 1
    else:
        for index, item in enumerate(user_menu):
            func = item.get("func", "")
            if normalize_help_key(func) == normalize_help_key(function_name):
                target_function = item
                target_index = index + 1
                break
        if not target_function:
            arg_key = normalize_help_key(function_name)
            for index, item in enumerate(user_menu):
                func = item.get("func", "")
                if arg_key and arg_key in normalize_help_key(func):
                    target_function = item
                    target_index = index + 1
                    break

    if not target_function:
        return None, HelpMarkdownIssue.FUNCTION_NOT_FOUND

    display_name = plugin_display_name(target_plugin)
    func_name = str(target_function.get("func", "未命名功能") or "未命名功能")
    perm_raw = effective_permission_avail_text(target_function)
    cd_raw = effective_command_cooldown_text(target_function)
    extra_sections: list[tuple[str, str]] = []
    if target_plugin.name == "maa" and func_name in {"绑定设备", "绑定 MAA 设备", "MAA HTTP"}:
        from pallas.core.plugin_coord import maa as maa_coord

        extra_sections.append(("MAA 对接地址", maa_coord.format_maa_http_setup_help()))

    return (
        FunctionDetailData(
            plugin=target_plugin,
            display_name=display_name,
            func_name=func_name,
            index=target_index,
            total=len(user_menu),
            say=help_say_phrase(target_function),
            scene=help_scene_text(target_function),
            perm=perm_raw or "—",
            cooldown=cd_raw or "—",
            brief=str(target_function.get("brief_des", "") or "暂无简介").strip(),
            detail=str(target_function.get("detail_des", "") or "").strip(),
            extra_sections=extra_sections,
        ),
        HelpMarkdownIssue.OK,
    )


@dataclass(frozen=True, slots=True)
class CommandHelpTarget:
    plugin_name: str
    plugin_display: str
    func_name: str


def command_match_tokens(item: dict[str, Any]) -> list[str]:
    """单条 menu 项可被「牛牛帮助 <口令>」直达的检索词：func 与去占位的口令。"""
    tokens: list[str] = []
    func = str(item.get("func", "") or "").strip()
    if func:
        tokens.append(func)
    say = help_say_phrase(item)
    if say and say != "—":
        for alt in _CMD_ALT_SPLIT_RE.split(say):
            alt = alt.strip()
            if not alt or _CMD_PLACEHOLDER_RE.search(alt):
                continue
            # 去掉口令后的补充说明，如「牛牛拉黑 + QQ 或 @」只取口令本体
            alt = re.split(r"\s*\+\s*", alt)[0].strip()
            if alt:
                tokens.append(alt)
    return tokens


def search_command_help_targets(identifier: str, plugins: list[Any]) -> list[CommandHelpTarget]:
    """在给定插件集合里把单条参数当作口令/功能名解析，精确优先、其次为口令的子串。"""
    key = normalize_help_key(identifier)
    if not key:
        return []

    exact: list[CommandHelpTarget] = []
    partial: list[CommandHelpTarget] = []
    exact_seen: set[tuple[str, str]] = set()
    partial_seen: set[tuple[str, str]] = set()

    for plugin in plugins:
        meta = getattr(plugin, "metadata", None)
        if meta is None or not getattr(meta, "extra", None):
            continue
        for item in iter_plugin_detail_menu(plugin, meta.extra.get("menu_data", [])):
            func = str(item.get("func", "") or "").strip()
            if not func:
                continue
            tokens = [t for t in (normalize_help_key(tok) for tok in command_match_tokens(item)) if t]
            if not tokens:
                continue
            dedup_key = (plugin.name or "", func)
            target = CommandHelpTarget(plugin.name or "", plugin_display_name(plugin), func)
            if key in tokens:
                if dedup_key not in exact_seen:
                    exact_seen.add(dedup_key)
                    exact.append(target)
            elif any(key in token for token in tokens):
                if dedup_key not in partial_seen:
                    partial_seen.add(dedup_key)
                    partial.append(target)

    return exact or partial


def find_command_help_targets(
    identifier: str,
    *,
    show_ignored: bool,
    ignored_plugins: list[str] | None,
) -> list[CommandHelpTarget]:
    """跨帮助总览插件解析口令/功能名，供「牛牛帮助 <口令>」直达功能详情页。"""
    from .plugin_manager import get_help_menu_plugins

    plugins = get_help_menu_plugins(show_ignored=show_ignored, ignored_plugins=ignored_plugins)
    return search_command_help_targets(identifier, plugins)
