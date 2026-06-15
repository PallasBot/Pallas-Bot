"""Matcher 确定性规则预筛：在 check_rule 前跳过明显不匹配的 handler（fail-open）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher

ActivationDecision = Literal["match", "miss", "unknown"]

_KNOWN_SAFE_RULE_NAMES = frozenset({
    "CommandRule",
    "ShellCommandRule",
    "RegexRule",
    "StartswithRule",
    "EndswithRule",
    "FullmatchRule",
    "KeywordsRule",
    "IsTypeRule",
    "ToMeRule",
})


@dataclass(frozen=True, slots=True)
class RuleDescriptor:
    kind: str
    value: object | None = None
    flags: int = 0
    ignorecase: bool = False


def normalize_rule_string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(str(item) for item in value if str(item))
    return ()


def normalize_nested_string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list | tuple | set | frozenset):
        out: list[str] = []
        for item in value:
            for sub in normalize_nested_string_tuple(item):
                if sub not in out:
                    out.append(sub)
        return tuple(out)
    return ()


def text_candidates(plain_text: str, raw_text: str) -> tuple[str, ...]:
    out: list[str] = []
    for text in (plain_text, raw_text):
        normalized = (text or "").strip()
        if normalized and normalized not in out:
            out.append(normalized)
    return tuple(out)


def normalize_command(text: str) -> str:
    return (text or "").strip().lower()


def command_matches_message(text: str, command: str) -> bool:
    cmd = normalize_command(command)
    if not cmd:
        return False
    normalized = normalize_command(text)
    if normalized == cmd:
        return True
    if normalized.startswith(cmd) and len(normalized) > len(cmd):
        return normalized[len(cmd)].isspace()
    return False


@lru_cache(maxsize=512)
def extract_matcher_rule_descriptors(matcher_cls: type[Matcher]) -> tuple[RuleDescriptor, ...]:
    from src.platform.ingress.matcher_activation import iter_matcher_checker_calls

    descriptors: list[RuleDescriptor] = []
    for call in iter_matcher_checker_calls(matcher_cls):
        call_module = call.__class__.__module__
        call_name = call.__class__.__name__
        if not call_module.startswith("nonebot.rule"):
            descriptors.append(RuleDescriptor("custom"))
            continue
        if call_name == "CommandRule":
            descriptors.append(RuleDescriptor("command", normalize_nested_string_tuple(getattr(call, "cmds", ()))))
        elif call_name == "ShellCommandRule":
            descriptors.append(
                RuleDescriptor("shell_command", normalize_nested_string_tuple(getattr(call, "cmds", ())))
            )
        elif call_name == "RegexRule":
            descriptors.append(
                RuleDescriptor("regex", getattr(call, "regex", ""), flags=int(getattr(call, "flags", 0) or 0))
            )
        elif call_name == "StartswithRule":
            descriptors.append(
                RuleDescriptor(
                    "startswith",
                    normalize_rule_string_tuple(getattr(call, "msg", ())),
                    ignorecase=bool(getattr(call, "ignorecase", False)),
                )
            )
        elif call_name == "EndswithRule":
            descriptors.append(
                RuleDescriptor(
                    "endswith",
                    normalize_rule_string_tuple(getattr(call, "msg", ())),
                    ignorecase=bool(getattr(call, "ignorecase", False)),
                )
            )
        elif call_name == "FullmatchRule":
            descriptors.append(
                RuleDescriptor(
                    "fullmatch",
                    normalize_rule_string_tuple(getattr(call, "msg", ())),
                    ignorecase=bool(getattr(call, "ignorecase", False)),
                )
            )
        elif call_name == "KeywordsRule":
            descriptors.append(RuleDescriptor("keywords", normalize_rule_string_tuple(getattr(call, "keywords", ()))))
        elif call_name == "IsTypeRule":
            descriptors.append(RuleDescriptor("is_type", getattr(call, "types", ())))
        elif call_name == "ToMeRule":
            descriptors.append(RuleDescriptor("to_me"))
        elif call_name in _KNOWN_SAFE_RULE_NAMES:
            descriptors.append(RuleDescriptor("custom"))
        else:
            descriptors.append(RuleDescriptor("custom"))
    return tuple(descriptors)


def matcher_rule_decision(
    descriptors: tuple[RuleDescriptor, ...],
    *,
    plain_text: str,
    raw_text: str,
    event: Event | None = None,
) -> ActivationDecision:
    if not descriptors:
        return "unknown"
    matched_any = False
    message_text = raw_text or plain_text
    plain_candidates = text_candidates(plain_text, raw_text)
    to_me = bool(getattr(event, "to_me", False)) if event is not None else False

    for descriptor in descriptors:
        kind = descriptor.kind
        if kind == "custom":
            return "unknown"
        if kind in {"command", "shell_command"}:
            commands: set[str] = set()
            value = descriptor.value
            if isinstance(value, str):
                commands.add(value)
            elif isinstance(value, list | tuple | set | frozenset):
                commands.update(str(item) for item in value if str(item))
            normalized_commands = {normalize_command(item) for item in commands if normalize_command(item)}
            if any(
                command_matches_message(text, command) for text in plain_candidates for command in normalized_commands
            ):
                matched_any = True
            else:
                return "miss"
        elif kind == "regex":
            pattern = str(descriptor.value or "")
            if not pattern:
                continue
            try:
                if re.search(pattern, message_text, descriptor.flags):
                    matched_any = True
                else:
                    return "miss"
            except re.error:
                return "unknown"
        elif kind == "startswith":
            values = descriptor.value if isinstance(descriptor.value, tuple) else ()
            prefixes = tuple(item.casefold() for item in values) if descriptor.ignorecase else values
            texts = tuple(item.casefold() for item in plain_candidates) if descriptor.ignorecase else plain_candidates
            if any(text.startswith(prefix) for text in texts for prefix in prefixes if prefix):
                matched_any = True
            else:
                return "miss"
        elif kind == "endswith":
            values = descriptor.value if isinstance(descriptor.value, tuple) else ()
            suffixes = tuple(item.casefold() for item in values) if descriptor.ignorecase else values
            texts = tuple(item.casefold() for item in plain_candidates) if descriptor.ignorecase else plain_candidates
            if any(text.endswith(suffix) for text in texts for suffix in suffixes if suffix):
                matched_any = True
            else:
                return "miss"
        elif kind == "fullmatch":
            values = descriptor.value if isinstance(descriptor.value, tuple) else ()
            patterns = tuple(item.casefold() for item in values) if descriptor.ignorecase else values
            texts = tuple(item.casefold() for item in plain_candidates) if descriptor.ignorecase else plain_candidates
            if any(text == pattern for text in texts for pattern in patterns if pattern):
                matched_any = True
            else:
                return "miss"
        elif kind == "keywords":
            values = descriptor.value if isinstance(descriptor.value, tuple) else ()
            if any(keyword in plain_text for keyword in values if keyword):
                matched_any = True
            else:
                return "miss"
        elif kind == "is_type":
            if event is None:
                return "unknown"
            event_type = event.get_type()
            types = descriptor.value if isinstance(descriptor.value, tuple) else ()
            if event_type in types:
                matched_any = True
            else:
                return "miss"
        elif kind == "to_me":
            if to_me:
                matched_any = True
            else:
                return "miss"
    if matched_any:
        return "match"
    return "unknown"


def matcher_prefilter_should_skip(
    matcher: type[Matcher],
    event: Event | None,
    plain_text: str,
    raw_text: str,
) -> bool:
    descriptors = extract_matcher_rule_descriptors(matcher)
    decision = matcher_rule_decision(
        descriptors,
        plain_text=plain_text,
        raw_text=raw_text,
        event=event,
    )
    return decision == "miss"


def apply_matcher_rule_prefilter(
    matchers: list[type[Matcher]],
    event: Event | None,
    plain_text: str,
    raw_text: str,
) -> list[type[Matcher]]:
    if not matchers or event is None:
        return matchers
    kept: list[type[Matcher]] = []
    for matcher in matchers:
        if matcher_prefilter_should_skip(matcher, event, plain_text, raw_text):
            continue
        kept.append(matcher)
    return kept
