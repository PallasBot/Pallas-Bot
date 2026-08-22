from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from nonebot import get_loaded_plugins

from pallas.core.foundation.command_prefix import strip_leading_command_marks
from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.platform.ingress.matcher_command_words import collect_command_words_for_matcher
from pallas.core.platform.ingress.plugin_command_plaintext import (
    _iter_trigger_parts,
    extract_command_prefixes_from_menu_data,
)
from pallas.core.platform.ingress.policy_registry import parse_fanout_policies
from pallas.core.platform.ingress.prefix_trie import PrefixModuleTrie

if TYPE_CHECKING:
    import re

    from nonebot.matcher import Matcher

_DEFAULT_PASSIVE_MODULES = frozenset({
    "repeater",
    "llm_chat",
    "greeting",
    "drink",
    "roulette",
})
_INDEX_CACHE: RouteIndexSnapshot | None = None


def chat_matcher_strict_enabled() -> bool:
    """闲聊是否只跑 passive/always_run/命中模块。默认开启。"""
    raw = repo_env_raw_value("PALLAS_CHAT_MATCHER_STRICT")
    if raw is None:
        return True
    text = str(raw).strip().lower()
    if text in ("0", "false", "no", "off"):
        return False
    return True


@dataclass(frozen=True, slots=True)
class RouteIndexSnapshot:
    prefix_to_modules: dict[str, frozenset[str]]
    exact_to_modules: dict[str, frozenset[str]]
    regex_entries: tuple[tuple[str, re.Pattern[str]], ...]
    always_run_modules: frozenset[str]
    passive_modules: frozenset[str]
    indexed_modules: frozenset[str]
    required_bot_capabilities: dict[str, str] = field(default_factory=dict)
    prefix_trie: PrefixModuleTrie | None = None


@dataclass(frozen=True, slots=True)
class RouteResolution:
    matched_modules: frozenset[str]
    index_hit: bool


def route_index_strict() -> bool:
    raw = repo_env_raw_value("PALLAS_ROUTE_INDEX_STRICT")
    if raw is None:
        return False
    text = str(raw).strip().lower()
    return text in ("1", "true", "yes", "on")


def route_index_enabled() -> bool:
    raw = repo_env_raw_value("PALLAS_ROUTE_INDEX_ENABLED")
    if raw is None:
        return True
    text = str(raw).strip().lower()
    if text in ("0", "false", "no", "off"):
        return False
    return True


def clear_route_index_cache() -> None:
    global _INDEX_CACHE
    _INDEX_CACHE = None
    matcher_module_key.cache_clear()


def plugin_module_key_from_plugin(plugin: object) -> str:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    mod = getattr(plugin, "module", None)
    module_name = getattr(mod, "__name__", "") if mod is not None else ""
    if not module_name:
        module_name = str(getattr(plugin, "module_name", "") or "")
    if not module_name:
        return "unknown"
    return canonical_plugin_package(module_name.rsplit(".", 1)[-1])


@lru_cache(maxsize=512)
def matcher_module_key(matcher: type[Matcher]) -> str:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    module_name = getattr(matcher, "plugin_name", None)
    if not module_name:
        return "unknown"
    text = str(module_name)
    parts = text.split(".")
    for part in reversed(parts):
        if part != "__init__":
            return canonical_plugin_package(part)
    return canonical_plugin_package(text.rsplit(".", 1)[-1])


def extract_exact_plaintexts_from_menu_data(
    menu_data: list[dict[str, Any]] | None,
    *,
    scene: str = "all",
) -> tuple[str, ...]:
    from pallas.core.platform.ingress.plugin_command_plaintext import menu_item_matches_scene

    exacts: list[str] = []
    for item in menu_data or []:
        if not menu_item_matches_scene(item, scene=scene):
            continue
        trigger = str(item.get("trigger_condition") or "").strip()
        if not trigger:
            continue
        for part in _iter_trigger_parts(trigger):
            if any(ch in part for ch in "〈<[@+"):
                continue
            text = part.strip()
            if len(text) >= 2 and text not in exacts:
                exacts.append(text)
    return tuple(exacts)


def extract_explicit_route_strings(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return ()
    seen: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def _add_module_mapping(
    mapping: dict[str, set[str]],
    key: str,
    module_key: str,
) -> None:
    text = (key or "").strip()
    if not text:
        return
    bucket = mapping.setdefault(text, set())
    bucket.add(module_key)


def build_route_index() -> RouteIndexSnapshot:
    prefix_map: dict[str, set[str]] = {}
    exact_map: dict[str, set[str]] = {}
    regex_entries: list[tuple[str, re.Pattern[str]]] = []
    always_run: set[str] = set()
    passive: set[str] = set(_DEFAULT_PASSIVE_MODULES)
    indexed: set[str] = set()
    required_capabilities: dict[str, str] = {}

    for plugin in get_loaded_plugins():
        module_key = plugin_module_key_from_plugin(plugin)
        meta = getattr(plugin, "metadata", None)
        extra = getattr(meta, "extra", None) if meta is not None else None
        if not isinstance(extra, dict):
            continue

        ingress_route = extra.get("ingress_route")
        if isinstance(ingress_route, dict):
            if ingress_route.get("always_run"):
                always_run.add(module_key)
            if ingress_route.get("passive"):
                passive.add(module_key)
            capability = ingress_route.get("required_bot_capability")
            if isinstance(capability, str) and capability.strip():
                required_capabilities[module_key] = capability.strip()

        menu_data = extra.get("menu_data")
        route_prefixes = extract_explicit_route_strings(extra.get("command_prefixes"))
        route_exacts = extract_explicit_route_strings(extra.get("exact_plaintexts"))
        if isinstance(menu_data, list):
            if not route_prefixes:
                route_prefixes = extract_command_prefixes_from_menu_data(menu_data, scene="group")
            if not route_exacts:
                route_exacts = extract_exact_plaintexts_from_menu_data(menu_data, scene="group")
        for prefix in route_prefixes:
            _add_module_mapping(prefix_map, prefix, module_key)
            indexed.add(module_key)
        for exact in route_exacts:
            _add_module_mapping(exact_map, exact, module_key)
            indexed.add(module_key)
        if isinstance(menu_data, list):
            for prefix in extract_command_prefixes_from_menu_data(menu_data, scene="group"):
                if prefix in route_prefixes:
                    continue
                _add_module_mapping(prefix_map, prefix, module_key)
                indexed.add(module_key)
            for exact in extract_exact_plaintexts_from_menu_data(menu_data, scene="group"):
                if exact in route_exacts:
                    continue
                _add_module_mapping(exact_map, exact, module_key)
                indexed.add(module_key)

        for fanout_raw in (extra.get("ingress_fanout"), extra.get("ingress_fanout_additional")):
            for entry in parse_fanout_policies(fanout_raw):
                indexed.add(module_key)
                for plain in entry.plaintexts:
                    _add_module_mapping(exact_map, plain, module_key)
                for prefix in entry.prefixes:
                    _add_module_mapping(prefix_map, prefix, module_key)
                regex_entries.extend((module_key, pattern) for pattern in entry.regexes)

        for matcher in getattr(plugin, "matcher", ()) or ():
            for word in collect_command_words_for_matcher(matcher):
                if word:
                    _add_module_mapping(prefix_map, word, module_key)
                    indexed.add(module_key)

    prefix_frozen = {key: frozenset(modules) for key, modules in prefix_map.items()}
    exact_frozen = {key: frozenset(modules) for key, modules in exact_map.items()}
    return RouteIndexSnapshot(
        prefix_to_modules=prefix_frozen,
        exact_to_modules=exact_frozen,
        regex_entries=tuple(regex_entries),
        always_run_modules=frozenset(always_run),
        passive_modules=frozenset(passive),
        indexed_modules=frozenset(indexed),
        required_bot_capabilities=required_capabilities,
        prefix_trie=PrefixModuleTrie.from_mapping(prefix_frozen),
    )


def get_route_index() -> RouteIndexSnapshot:
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        _INDEX_CACHE = build_route_index()
    return _INDEX_CACHE


def _prefix_trie_for(index: RouteIndexSnapshot) -> PrefixModuleTrie:
    trie = index.prefix_trie
    if trie is not None:
        return trie
    return PrefixModuleTrie.from_mapping(index.prefix_to_modules)


def resolve_message_route(plain: str) -> RouteResolution:
    started = time.perf_counter()
    try:
        text = strip_leading_command_marks((plain or "").strip())
        if not text:
            return RouteResolution(frozenset(), False)

        index = get_route_index()
        matched: set[str] = set()
        hit = False

        if text in index.exact_to_modules:
            matched.update(index.exact_to_modules[text])
            hit = True

        prefix_modules = _prefix_trie_for(index).longest_prefix_modules(text)
        if prefix_modules:
            matched.update(prefix_modules)
            hit = True

        for module_key, pattern in index.regex_entries:
            if pattern.match(text):
                matched.add(module_key)
                hit = True

        return RouteResolution(frozenset(matched), hit)
    finally:
        from pallas.core.platform.ingress.hotpath_metrics import record_route_resolve_ms

        record_route_resolve_ms((time.perf_counter() - started) * 1000.0)


def matcher_always_runs(matcher: type[Matcher], index: RouteIndexSnapshot) -> bool:
    module_key = matcher_module_key(matcher)
    return module_key in index.always_run_modules or module_key in index.passive_modules
