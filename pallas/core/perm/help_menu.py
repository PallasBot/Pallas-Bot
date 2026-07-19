"""帮助图 menu_data 约定：面向用户的「怎么说 / 场景」与实现侧 trigger_method 分离。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

from .menu_display import raw_trigger_condition

# trigger_condition：用户要发送的口令或可见触发说明
# trigger_scene：私聊 / 群内 / 自动
# trigger_method：实现方式，帮助图不展示
# help_audience：superuser 时不进入用户帮助图（"maintainer" 为历史别名，等同 superuser）

_SCENE_IN_PAREN_RE = re.compile(r"[（(]\s*(私聊|群内|群聊)\s*[）)]")

_METHOD_SCENE_FALLBACK: dict[str, str] = {
    "on_cmd": "发命令",
    "on_command": "发命令",
    "命令": "发命令",
    "on_message": "发消息",
    "on_notice": "自动",
    "scheduler": "自动",
    "http": "—",
    "event_preprocessor": "自动",
}


def is_user_help_menu_item(item: dict[str, Any]) -> bool:
    audience = str(item.get("help_audience", "user") or "user").strip().lower()
    # "maintainer" 为历史别名，等同 superuser（项目无独立维护者权限等级）。
    return audience not in {"maintainer", "superuser"}


def plugin_help_audience(plugin: Any) -> str:
    """PluginMetadata.extra.help_audience，缺省 user。"""
    meta = getattr(plugin, "metadata", None)
    if meta is None:
        return "user"
    extra = getattr(meta, "extra", None)
    if not isinstance(extra, dict):
        return "user"
    return str(extra.get("help_audience", "user") or "user").strip().lower()


def is_user_help_plugin(plugin: Any) -> bool:
    """插件级 help_audience 为 superuser 时不进入用户帮助总览（maintainer 为历史别名）。"""
    return plugin_help_audience(plugin) not in {"maintainer", "superuser"}


def iter_user_help_menu(menu_data: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for item in menu_data:
        if is_user_help_menu_item(item):
            yield item


def iter_plugin_detail_menu(plugin: Any, menu_data: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """插件详情页的 menu 条目。

    超管专属插件（``is_user_help_plugin`` 为假）整体已对普通用户隐藏，
    其详情页只有超管才打得开，因此展示全部条目；普通插件仍按 user 受众过滤。
    """
    if not is_user_help_plugin(plugin):
        yield from menu_data
        return
    yield from iter_user_help_menu(menu_data)


def help_say_phrase(item: dict[str, Any]) -> str:
    """帮助表「怎么说」列：口令或用户可见说明。"""
    raw = raw_trigger_condition(item)
    if raw in ("未知", ""):
        return "—"
    text = raw.strip()
    text = _SCENE_IN_PAREN_RE.sub("", text).strip()
    return text or raw


def help_scene_text(item: dict[str, Any]) -> str:
    """帮助表「场景」列：私聊 / 群内 / 自动。"""
    explicit = str(item.get("trigger_scene", "") or "").strip()
    if explicit:
        return explicit
    raw = raw_trigger_condition(item)
    m = _SCENE_IN_PAREN_RE.search(raw)
    if m:
        word = m.group(1)
        return "群内" if word == "群聊" else word
    method = str(item.get("trigger_method", "") or "").strip().lower()
    if "/" in method:
        parts = [_METHOD_SCENE_FALLBACK.get(p.strip(), "") for p in method.split("/")]
        parts = [p for p in parts if p and p != "—"]
        if parts:
            return parts[0] if len(set(parts)) == 1 else "多种"
    return _METHOD_SCENE_FALLBACK.get(method, "—")
