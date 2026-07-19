"""从 PluginMetadata.extra 聚合 ingress fanout 策略，减少 fanout_bypass 中心改动。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from nonebot import get_loaded_plugins

from pallas.core.foundation.command_prefix import matches_command_prefix

_TRAILING_PUNCT = "！!？?。.,…~～"
_POLICIES_CACHE: tuple[FanoutPolicyEntry, ...] | None = None


class FanoutScope(StrEnum):
    ALWAYS = "always"
    UNIFIED_ONLY = "unified_only"
    SHARD_ONLY = "shard_only"


@dataclass(frozen=True, slots=True)
class FanoutPolicyEntry:
    scope: FanoutScope
    plaintexts: frozenset[str] = frozenset()
    prefixes: frozenset[str] = frozenset()
    regexes: tuple[re.Pattern[str], ...] = ()
    normalize_trailing_punct: bool = False


def normalize_ingress_trailing_punct(text: str) -> str:
    plain = (text or "").strip()
    while plain and plain[-1] in _TRAILING_PUNCT:
        plain = plain[:-1]
    return plain


def clear_ingress_policy_cache() -> None:
    global _POLICIES_CACHE
    _POLICIES_CACHE = None


def parse_fanout_scope(raw: object, *, default: FanoutScope = FanoutScope.ALWAYS) -> FanoutScope:
    text = str(raw or "").strip().lower()
    if text in ("unified", "unified_only"):
        return FanoutScope.UNIFIED_ONLY
    if text in ("shard", "shard_only"):
        return FanoutScope.SHARD_ONLY
    if text in ("always", ""):
        return FanoutScope.ALWAYS
    return default


def parse_fanout_policy(raw: dict[str, Any]) -> FanoutPolicyEntry | None:
    scope = parse_fanout_scope(raw.get("scope"), default=FanoutScope.ALWAYS)

    plain_raw = raw.get("plaintexts")
    plaintexts: set[str] = set()
    if isinstance(plain_raw, (list, tuple)):
        plaintexts.update(str(item).strip() for item in plain_raw if str(item).strip())

    prefix_raw = raw.get("prefixes")
    prefixes: set[str] = set()
    if isinstance(prefix_raw, (list, tuple)):
        prefixes.update(str(item).strip() for item in prefix_raw if str(item).strip())

    regex_raw = raw.get("regexes")
    regexes: list[re.Pattern[str]] = []
    if isinstance(regex_raw, (list, tuple)):
        for item in regex_raw:
            pattern = str(item).strip()
            if pattern:
                regexes.append(re.compile(pattern))

    normalize = raw.get("normalize_trailing_punct", False)
    if not isinstance(normalize, bool):
        normalize = False

    if not plaintexts and not prefixes and not regexes:
        return None

    return FanoutPolicyEntry(
        scope=scope,
        plaintexts=frozenset(plaintexts),
        prefixes=frozenset(prefixes),
        regexes=tuple(regexes),
        normalize_trailing_punct=normalize,
    )


def fanout_policy_for_plugin(plugin_name: str) -> FanoutPolicyEntry | None:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    name = canonical_plugin_package((plugin_name or "").strip())
    if not name:
        return None
    for plugin in get_loaded_plugins():
        if canonical_plugin_package(str(getattr(plugin, "name", "")).strip()) != name:
            continue
        meta = getattr(plugin, "metadata", None)
        extra = getattr(meta, "extra", None) if meta is not None else None
        if not isinstance(extra, dict):
            return None
        raw = extra.get("ingress_fanout")
        if not isinstance(raw, dict):
            return None
        return parse_fanout_policy(raw)
    return None


def text_matches_plugin_fanout(plain: str, plugin_name: str) -> bool:
    entry = fanout_policy_for_plugin(plugin_name)
    if entry is None:
        return False
    return policy_matches_text(entry, plain)


def loaded_fanout_policies() -> tuple[FanoutPolicyEntry, ...]:
    global _POLICIES_CACHE
    if _POLICIES_CACHE is not None:
        return _POLICIES_CACHE

    entries: list[FanoutPolicyEntry] = []
    for plugin in get_loaded_plugins():
        entry = fanout_policy_for_plugin(str(getattr(plugin, "name", "")).strip())
        if entry is not None:
            entries.append(entry)
    _POLICIES_CACHE = tuple(entries)
    return _POLICIES_CACHE


def policy_matches_text(entry: FanoutPolicyEntry, plain: str) -> bool:
    text = normalize_ingress_trailing_punct(plain) if entry.normalize_trailing_punct else (plain or "").strip()
    if not text:
        return False
    if text in entry.plaintexts:
        return True
    if any(matches_command_prefix(text, prefix) for prefix in entry.prefixes):
        return True
    return any(pattern.match(text) for pattern in entry.regexes)


def fanout_policy_bypasses_claim(plain: str, *, sharding_active: bool) -> bool:
    for entry in loaded_fanout_policies():
        if entry.scope == FanoutScope.UNIFIED_ONLY and sharding_active:
            continue
        if entry.scope == FanoutScope.SHARD_ONLY and not sharding_active:
            continue
        if policy_matches_text(entry, plain):
            return True
    return False
