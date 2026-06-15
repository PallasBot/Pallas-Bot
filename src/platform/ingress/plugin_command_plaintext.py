"""插件命令明文识别：供 ingress / repeater 绕开命令类消息。"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from nonebot import get_loaded_plugins
from nonebot.rule import TrieRule

from src.foundation.command_prefix import matches_command_prefix, strip_leading_command_marks

_TRIGGER_SPLIT_RE = re.compile(r"\s*/\s*|[、，,]")
_TOKEN_SPLIT_RE = re.compile(r"[\s<＜〈\[(（(:：]")
_PLUGIN_PREFIX_CACHE_VALUE: tuple[str, ...] | None = None


def _iter_trigger_parts(trigger_condition: str) -> list[str]:
    return [part.strip() for part in _TRIGGER_SPLIT_RE.split((trigger_condition or "").strip()) if part.strip()]


def _extract_literal_prefix(part: str) -> str | None:
    raw = (part or "").strip()
    if not raw or raw.startswith("@") or "+" in raw:
        return None
    head = _TOKEN_SPLIT_RE.split(raw, maxsplit=1)[0].strip()
    if not head or any(ch in head for ch in "@+"):
        return None
    # 「牛牛 + 文本」这类聊天触发不应视作命令。
    if head == "牛牛" and ("文本" in raw or raw == "牛牛"):
        return None
    return head if len(head) >= 2 else None


def extract_command_prefixes_from_menu_data(menu_data: list[dict[str, Any]] | None) -> tuple[str, ...]:
    prefixes: list[str] = []
    for item in menu_data or []:
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
        menu_data = extra.get("menu_data") if isinstance(extra, dict) else None
        for prefix in extract_command_prefixes_from_menu_data(menu_data):
            if prefix not in prefixes:
                prefixes.append(prefix)
    _PLUGIN_PREFIX_CACHE_VALUE = tuple(prefixes)
    return _PLUGIN_PREFIX_CACHE_VALUE


def clear_plugin_command_plaintext_cache() -> None:
    global _PLUGIN_PREFIX_CACHE_VALUE

    _PLUGIN_PREFIX_CACHE_VALUE = None
    is_plugin_command_plaintext.cache_clear()
    from src.platform.ingress.hosted_activity_gate import clear_hosted_activity_ingress_cache
    from src.platform.ingress.policy_registry import clear_ingress_policy_cache

    clear_hosted_activity_ingress_cache()
    clear_ingress_policy_cache()


@lru_cache(maxsize=2048)
def is_plugin_command_plaintext(text: str) -> bool:
    plain = strip_leading_command_marks(text)
    if not plain:
        return False
    if TrieRule.prefix.longest_prefix(plain):
        return True
    return any(matches_command_prefix(plain, prefix) for prefix in _loaded_plugin_command_prefixes())
