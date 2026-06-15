"""帮助：按插件名 / 展示名 / 别名解析。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .plugin_aliases import aliases_for_plugin

if TYPE_CHECKING:
    from collections.abc import Iterable

_WS_RE = re.compile(r"[\s\u3000]+")

# 完全匹配
_SCORE_EXACT = 100
# 子串匹配
_SCORE_SUBSTRING = 50


def normalize_help_key(text: str) -> str:
    """忽略大小写与中日韩空格，便于「MAA远控」匹配「MAA 远控」。"""
    return _WS_RE.sub("", (text or "").strip().casefold())


def iter_plugin_lookup_tokens(plugin: Any) -> list[str]:
    """插件所有可检索名称。"""
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str | None) -> None:
        if not raw:
            return
        s = str(raw).strip()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s)

    add(getattr(plugin, "name", None))
    meta = getattr(plugin, "metadata", None)
    if meta is not None:
        add(getattr(meta, "name", None))
        extra = getattr(meta, "extra", None)
        if isinstance(extra, dict):
            aliases = extra.get("help_aliases")
            if isinstance(aliases, str):
                add(aliases)
            elif isinstance(aliases, (list, tuple)):
                for item in aliases:
                    add(str(item) if item is not None else None)

    add_aliases = aliases_for_plugin(getattr(plugin, "name", None) or "")
    for alias in add_aliases:
        add(alias)

    return out


def plugin_match_score(plugin: Any, raw_key: str) -> int:
    key_norm = normalize_help_key(raw_key)
    if not key_norm:
        return 0

    best = 0
    for token in iter_plugin_lookup_tokens(plugin):
        token_norm = normalize_help_key(token)
        if not token_norm:
            continue
        if key_norm == token_norm:
            return _SCORE_EXACT
        if key_norm in token_norm or token_norm in key_norm:
            # 更长公共片段优先，减少「牛」误中过多插件时的并列
            overlap = min(len(key_norm), len(token_norm))
            if key_norm in token_norm:
                overlap = len(key_norm)
            elif token_norm in key_norm:
                overlap = len(token_norm)
            best = max(best, _SCORE_SUBSTRING + min(overlap, 40))
    return best


def find_matching_plugins(raw_key: str, plugins: Iterable[Any]) -> list[Any]:
    """返回得分最高的一组插件；无匹配或并列最高分时可有多条。"""
    key = (raw_key or "").strip()
    if not key:
        return []

    scored: list[tuple[int, Any]] = []
    for plugin in plugins:
        if not getattr(plugin, "name", None):
            continue
        score = plugin_match_score(plugin, key)
        if score > 0:
            scored.append((score, plugin))

    if not scored:
        return []

    max_score = max(score for score, _ in scored)
    return [plugin for score, plugin in scored if score == max_score]
