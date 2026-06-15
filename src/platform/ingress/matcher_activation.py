from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

from nonebot.consts import CMD_KEY
from nonebot.rule import TrieRule

from src.foundation.command_prefix import strip_leading_command_marks
from src.platform.ingress.matcher_rule_prefilter import apply_matcher_rule_prefilter
from src.platform.ingress.plugin_command_plaintext import is_plugin_command_plaintext
from src.platform.ingress.route_index import (
    RouteIndexSnapshot,
    RouteResolution,
    get_route_index,
    matcher_always_runs,
    matcher_module_key,
    resolve_message_route,
    route_index_enabled,
    route_index_strict,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher

_COMMAND_CHECKER_NAMES = frozenset({"CommandRule", "ShellCommandRule"})
_LEADING_PLACEHOLDER_RE = re.compile(r"^(?:\s*(?:\[[^\]]*]|\<[^>]*>))+\s*")


def iter_matcher_checker_calls(matcher: type[Matcher]):
    checkers = tuple(getattr(getattr(matcher, "rule", None), "checkers", ()))
    for checker in checkers:
        call = getattr(checker, "call", None)
        if call is None:
            continue
        nested = getattr(call, "checkers", None)
        if nested:
            for inner in nested:
                inner_call = getattr(inner, "call", None)
                if inner_call is not None:
                    yield inner_call
            continue
        yield call


def _checker_name(checker: object) -> str:
    return type(checker).__name__


@lru_cache(maxsize=512)
def matcher_is_command_only(matcher: type[Matcher]) -> bool:
    calls = tuple(iter_matcher_checker_calls(matcher))
    if not calls:
        return False
    for call in calls:
        if _checker_name(call) not in _COMMAND_CHECKER_NAMES:
            return False
    return True


def normalize_dispatch_plain_text(text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return ""
    normalized = _LEADING_PLACEHOLDER_RE.sub("", normalized).strip()
    return strip_leading_command_marks(normalized)


def event_dispatch_texts(event: Event) -> tuple[str, str]:
    raw = getattr(event, "raw_message", None)
    raw_text = normalize_dispatch_plain_text(raw) if isinstance(raw, str) else ""
    plain = normalize_dispatch_plain_text((event.get_plaintext() or "").strip())
    if not plain and raw_text:
        plain = raw_text
    return plain, raw_text


def legacy_command_traffic(plain: str) -> bool:
    if TrieRule.prefix.longest_prefix(plain):
        return True
    return is_plugin_command_plaintext(plain)


def resolve_route_for_event(event: Event) -> RouteResolution | None:
    if not route_index_enabled():
        return None
    plain, _ = event_dispatch_texts(event)
    return resolve_message_route(plain)


def event_command_traffic(
    event: Event,
    state: dict,
    *,
    resolution: RouteResolution | None = None,
) -> bool:
    if state.get(CMD_KEY) is not None:
        return True
    plain, _ = event_dispatch_texts(event)
    if not plain:
        return False
    if resolution is not None:
        if resolution.index_hit:
            return True
        if not route_index_strict():
            return legacy_command_traffic(plain)
        return False
    return legacy_command_traffic(plain)


def select_priority_matchers(
    priority_matchers: list[type[Matcher]],
    *,
    command_traffic: bool,
    resolution: RouteResolution | None = None,
    event: Event | None = None,
) -> list[type[Matcher]]:
    if not priority_matchers:
        return priority_matchers

    if not route_index_enabled() or resolution is None:
        if command_traffic:
            selected = priority_matchers
        else:
            selected = [matcher for matcher in priority_matchers if not matcher_is_command_only(matcher)]
    else:
        index = get_route_index()
        apply_index_filter = resolution.index_hit or route_index_strict()
        if not apply_index_filter:
            if command_traffic:
                selected = priority_matchers
            else:
                selected = [matcher for matcher in priority_matchers if not matcher_is_command_only(matcher)]
        elif command_traffic:
            selected = filter_command_matchers(priority_matchers, resolution, index)
        else:
            selected = filter_chatter_matchers(priority_matchers, resolution, index)

    if event is None:
        return selected
    plain, raw_text = event_dispatch_texts(event)
    return apply_matcher_rule_prefilter(selected, event, plain, raw_text)


def filter_chatter_matchers(
    priority_matchers: list[type[Matcher]],
    resolution: RouteResolution,
    index: RouteIndexSnapshot,
) -> list[type[Matcher]]:
    matched = resolution.matched_modules
    selected: list[type[Matcher]] = []
    for matcher in priority_matchers:
        if matcher_is_command_only(matcher):
            continue
        if matcher_always_runs(matcher, index):
            selected.append(matcher)
            continue
        module_key = matcher_module_key(matcher)
        if module_key in index.indexed_modules and module_key not in matched:
            continue
        selected.append(matcher)
    return selected


def filter_command_matchers(
    priority_matchers: list[type[Matcher]],
    resolution: RouteResolution,
    index: RouteIndexSnapshot,
) -> list[type[Matcher]]:
    matched = resolution.matched_modules
    selected: list[type[Matcher]] = []
    for matcher in priority_matchers:
        if getattr(matcher, "block", False):
            selected.append(matcher)
            continue
        if matcher_always_runs(matcher, index):
            selected.append(matcher)
            continue
        if matcher_module_key(matcher) in matched:
            selected.append(matcher)
    return selected
