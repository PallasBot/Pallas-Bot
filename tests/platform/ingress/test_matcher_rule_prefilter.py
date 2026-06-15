from __future__ import annotations

from unittest.mock import MagicMock

from nonebot.internal.rule import Rule
from nonebot.rule import command, startswith

from src.platform.ingress import matcher_rule_prefilter as prefilter


class _FooCommandMatcher:
    rule = Rule(command("foo"))


class _BarStartMatcher:
    rule = Rule(startswith("bar"))


def test_command_rule_miss():
    descriptors = prefilter.extract_matcher_rule_descriptors(_FooCommandMatcher)
    assert (
        prefilter.matcher_rule_decision(
            descriptors,
            plain_text="今天天气不错",
            raw_text="今天天气不错",
        )
        == "miss"
    )


def test_command_rule_match():
    descriptors = prefilter.extract_matcher_rule_descriptors(_FooCommandMatcher)
    assert (
        prefilter.matcher_rule_decision(
            descriptors,
            plain_text="foo",
            raw_text="foo",
        )
        == "match"
    )


def test_startswith_miss():
    descriptors = prefilter.extract_matcher_rule_descriptors(_BarStartMatcher)
    assert (
        prefilter.matcher_rule_decision(
            descriptors,
            plain_text="zzz",
            raw_text="zzz",
        )
        == "miss"
    )


def test_apply_prefilter_skips_miss():
    event = MagicMock()
    event.get_plaintext.return_value = "闲聊"
    event.raw_message = "闲聊"
    event.to_me = False
    event.get_type.return_value = "message"
    kept = prefilter.apply_matcher_rule_prefilter(
        [_FooCommandMatcher, _BarStartMatcher],
        event,
        "闲聊",
        "闲聊",
    )
    assert _FooCommandMatcher not in kept
    assert _BarStartMatcher not in kept
