"""插件命令明文识别：供 ingress / repeater 绕开命令类消息。"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Literal

from nonebot import get_loaded_plugins
from nonebot.rule import TrieRule

from pallas.core.foundation.command_prefix import strip_leading_command_marks

# 别名命令用「 / 」分隔（两侧需空白），避免拆开「图片/文字」这类说明
_TRIGGER_SPLIT_RE = re.compile(r"\s+/\s+|[、，,]")
_TOKEN_SPLIT_RE = re.compile(r"[\s<＜〈\[(（(:：]")
_PLUGIN_PREFIX_CACHE_VALUE: tuple[str, ...] | None = None
_PLUGIN_PREFIX_TRIE = None
_GROUP_PLUGIN_PREFIX_CACHE_VALUE: tuple[str, ...] | None = None
_GROUP_PLUGIN_PREFIX_TRIE = None


def _iter_trigger_parts(trigger_condition: str) -> list[str]:
    return [part.strip() for part in _TRIGGER_SPLIT_RE.split((trigger_condition or "").strip()) if part.strip()]


def _extract_literal_prefix(part: str) -> str | None:
    raw = (part or "").strip()
    if not raw or raw.startswith("@"):
        return None
    # 「命令 + 参数说明」只取 + 左侧；「牛牛 + 文本」整段仍不当命令
    if "+" in raw:
        left, _, right = raw.partition("+")
        left = left.strip()
        right = right.strip()
        if left == "牛牛" and (not right or "文本" in right):
            return None
        raw = left
        if not raw:
            return None
    head = _TOKEN_SPLIT_RE.split(raw, maxsplit=1)[0].strip()
    if not head or any(ch in head for ch in "@+"):
        return None
    # 裸「牛牛」不当命令前缀（避免抢走「牛牛 xxx」闲聊）
    if head == "牛牛" and (raw == "牛牛" or "文本" in raw):
        return None
    return head if len(head) >= 2 else None


def menu_item_matches_scene(item: dict[str, Any], *, scene: Literal["all", "group"] = "all") -> bool:
    if scene == "all":
        return True
    return str(item.get("trigger_scene") or "").strip() != "私聊"


def extract_command_prefixes_from_menu_data(
    menu_data: list[dict[str, Any]] | None,
    *,
    scene: Literal["all", "group"] = "all",
) -> tuple[str, ...]:
    prefixes: list[str] = []
    for item in menu_data or []:
        if not menu_item_matches_scene(item, scene=scene):
            continue
        trigger = str(item.get("trigger_condition") or "").strip()
        if not trigger:
            continue
        for part in _iter_trigger_parts(trigger):
            prefix = _extract_literal_prefix(part)
            if prefix and prefix not in prefixes:
                prefixes.append(prefix)
    return tuple(prefixes)


def _loaded_plugin_command_prefixes() -> tuple[str, ...]:
    global _PLUGIN_PREFIX_CACHE_VALUE
    if _PLUGIN_PREFIX_CACHE_VALUE is not None:
        return _PLUGIN_PREFIX_CACHE_VALUE

    plugins = tuple(get_loaded_plugins())
    prefixes: list[str] = []
    for plugin in plugins:
        meta = getattr(plugin, "metadata", None)
        extra = getattr(meta, "extra", None) if meta is not None else None
        if not isinstance(extra, dict):
            continue
        explicit = extra.get("command_prefixes")
        if isinstance(explicit, (list, tuple)):
            for prefix in explicit:
                item = str(prefix or "").strip()
                if item and item not in prefixes:
                    prefixes.append(item)
        menu_data = extra.get("menu_data")
        for prefix in extract_command_prefixes_from_menu_data(menu_data if isinstance(menu_data, list) else None):
            if prefix not in prefixes:
                prefixes.append(prefix)
    _PLUGIN_PREFIX_CACHE_VALUE = tuple(prefixes)
    return _PLUGIN_PREFIX_CACHE_VALUE


def _loaded_group_plugin_command_prefixes() -> tuple[str, ...]:
    global _GROUP_PLUGIN_PREFIX_CACHE_VALUE
    if _GROUP_PLUGIN_PREFIX_CACHE_VALUE is not None:
        return _GROUP_PLUGIN_PREFIX_CACHE_VALUE

    prefixes: list[str] = []
    for plugin in get_loaded_plugins():
        meta = getattr(plugin, "metadata", None)
        extra = getattr(meta, "extra", None) if meta is not None else None
        if not isinstance(extra, dict):
            continue
        explicit = extra.get("command_prefixes")
        if isinstance(explicit, (list, tuple)):
            for prefix in explicit:
                item = str(prefix or "").strip()
                if item and item not in prefixes:
                    prefixes.append(item)
        menu_data = extra.get("menu_data")
        for prefix in extract_command_prefixes_from_menu_data(
            menu_data if isinstance(menu_data, list) else None,
            scene="group",
        ):
            if prefix not in prefixes:
                prefixes.append(prefix)
    _GROUP_PLUGIN_PREFIX_CACHE_VALUE = tuple(prefixes)
    return _GROUP_PLUGIN_PREFIX_CACHE_VALUE


def clear_plugin_command_plaintext_cache() -> None:
    global _GROUP_PLUGIN_PREFIX_CACHE_VALUE, _GROUP_PLUGIN_PREFIX_TRIE, _PLUGIN_PREFIX_CACHE_VALUE, _PLUGIN_PREFIX_TRIE

    _PLUGIN_PREFIX_CACHE_VALUE = None
    _PLUGIN_PREFIX_TRIE = None
    _GROUP_PLUGIN_PREFIX_CACHE_VALUE = None
    _GROUP_PLUGIN_PREFIX_TRIE = None
    is_plugin_command_plaintext.cache_clear()
    is_group_plugin_command_plaintext.cache_clear()
    from pallas.core.foundation.command_prefix import clear_command_start_cache
    from pallas.core.platform.ingress.hosted_activity_gate import clear_hosted_activity_ingress_cache
    from pallas.core.platform.ingress.policy_registry import clear_ingress_policy_cache

    clear_command_start_cache()
    clear_hosted_activity_ingress_cache()
    clear_ingress_policy_cache()
    from pallas.core.platform.ingress.route_index import clear_route_index_cache

    clear_route_index_cache()
    from pallas.core.platform.ingress.dispatch_lanes import clear_dispatch_lanes_cache

    clear_dispatch_lanes_cache()


def _plugin_prefix_trie():
    global _PLUGIN_PREFIX_TRIE
    if _PLUGIN_PREFIX_TRIE is None:
        from pallas.core.platform.ingress.prefix_trie import PrefixModuleTrie

        _PLUGIN_PREFIX_TRIE = PrefixModuleTrie.from_prefixes(_loaded_plugin_command_prefixes())
    return _PLUGIN_PREFIX_TRIE


def _group_plugin_prefix_trie():
    global _GROUP_PLUGIN_PREFIX_TRIE
    if _GROUP_PLUGIN_PREFIX_TRIE is None:
        from pallas.core.platform.ingress.prefix_trie import PrefixModuleTrie

        _GROUP_PLUGIN_PREFIX_TRIE = PrefixModuleTrie.from_prefixes(_loaded_group_plugin_command_prefixes())
    return _GROUP_PLUGIN_PREFIX_TRIE


@lru_cache(maxsize=2048)
def is_plugin_command_plaintext(text: str) -> bool:
    plain = strip_leading_command_marks(text)
    if not plain:
        return False
    if TrieRule.prefix.longest_prefix(plain):
        return True
    return _plugin_prefix_trie().has_any_prefix(plain)


@lru_cache(maxsize=2048)
def is_group_plugin_command_plaintext(text: str) -> bool:
    plain = strip_leading_command_marks(text)
    if not plain:
        return False
    return _group_plugin_prefix_trie().has_any_prefix(plain)
