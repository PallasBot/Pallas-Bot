from __future__ import annotations

import math
import random

import pytest

from pallas.product.llm.inference_params import chat_reply_token_budget
from pallas.product.llm.reply_shape import resolve_reply_shape, resolve_short_reply_split_decision
from pallas.product.llm.turn_policy import TurnPolicy
from pallas.product.persona.group_expression_profile import GroupExpressionProfile, GroupReplyShapeHint


def make_turn_policy(*, seriousness: str = "casual", needs_tool: bool = False) -> TurnPolicy:
    return TurnPolicy(
        reply_target="answer",
        seriousness=seriousness,
        social_action="ANSWER",
        allow_teasing=seriousness == "casual",
        allow_affection=True,
        needs_tool=needs_tool,
        needs_grounding=needs_tool,
    )


def test_casual_chat_defaults_to_one_or_two_short_bubbles() -> None:
    policy = resolve_reply_shape(make_turn_policy(), None)

    assert 1 <= policy.preferred_bubbles <= 3
    assert policy.max_bubbles <= 5
    assert (policy.target_chars_min, policy.target_chars_max) == (4, 18)
    assert policy.total_length_band == "short"
    assert policy.max_output_tokens == chat_reply_token_budget("casual")


def test_casual_chat_without_profile_randomizes_bubble_count_across_range() -> None:
    seen: set[int] = set()
    for seed in range(200):
        policy = resolve_reply_shape(make_turn_policy(), None, rng=random.Random(seed))
        seen.add(policy.preferred_bubbles)
        assert policy.max_bubbles <= 5
        assert policy.total_length_band == "short"
    assert seen == {1, 2, 3}


def test_casual_seeded_bubble_count_is_deterministic() -> None:
    first = resolve_reply_shape(make_turn_policy(), None, rng=random.Random(7))
    second = resolve_reply_shape(make_turn_policy(), None, rng=random.Random(7))
    assert first.preferred_bubbles == second.preferred_bubbles


def test_short_band_split_decision_randomizes_keep_single() -> None:
    kept = split = 0
    for seed in range(200):
        keep = resolve_short_reply_split_decision(
            band="short",
            randomize_enabled=True,
            keep_rate=0.4,
            rng=random.Random(seed),
        )
        if keep:
            kept += 1
        else:
            split += 1
    assert kept > 0
    assert split > 0


def test_short_band_split_decision_disabled_or_non_short_always_splits() -> None:
    assert not resolve_short_reply_split_decision(
        band="short",
        randomize_enabled=False,
        keep_rate=0.4,
        rng=random.Random(0),
    )
    assert not resolve_short_reply_split_decision(
        band="complete",
        randomize_enabled=True,
        keep_rate=1.0,
    )


def test_short_band_split_decision_seeded_is_deterministic() -> None:
    first = resolve_short_reply_split_decision(
        band="short",
        randomize_enabled=True,
        keep_rate=0.4,
        rng=random.Random(7),
    )
    second = resolve_short_reply_split_decision(
        band="short",
        randomize_enabled=True,
        keep_rate=0.4,
        rng=random.Random(7),
    )
    assert first == second


def test_group_shape_can_supply_three_beat_ceiling_and_rhythm() -> None:
    profile = GroupExpressionProfile(
        reply_shape=GroupReplyShapeHint(
            bubble_count_p50=2,
            bubble_count_p90=8,
            segment_char_length_p50=7,
            rhythm_distribution={"multi": 0.7, "single": 0.3},
        )
    )

    policy = resolve_reply_shape(make_turn_policy(), profile)

    assert policy.preferred_bubbles == 2
    assert policy.max_bubbles == 5
    assert policy.rhythm == "multi"
    assert (policy.target_chars_min, policy.target_chars_max) == (4, 18)


def test_serious_turn_prioritizes_complete_answer_over_short_bubble_prior() -> None:
    profile = GroupExpressionProfile(
        reply_shape=GroupReplyShapeHint(
            length_pref="short",
            bubble_count_p50=3,
            segment_char_length_p50=4,
            segment_char_length_p90=6,
        )
    )

    policy = resolve_reply_shape(make_turn_policy(seriousness="serious"), profile)

    assert policy.preferred_bubbles == 1
    assert policy.target_chars_max > 18
    assert policy.total_length_band == "complete"
    assert policy.max_output_tokens == chat_reply_token_budget("serious")


def test_tool_budget_is_not_truncated_by_legacy_short_preference() -> None:
    short_profile = GroupExpressionProfile(
        reply_shape=GroupReplyShapeHint(
            length_pref="short",
            bubble_count_p50=1,
            segment_char_length_p50=4,
            segment_char_length_p90=6,
        )
    )

    short = resolve_reply_shape(make_turn_policy(needs_tool=True), short_profile)
    baseline = resolve_reply_shape(make_turn_policy(needs_tool=True), None)

    assert short.max_output_tokens == baseline.max_output_tokens
    assert short.max_output_tokens == chat_reply_token_budget("tool")
    assert short.target_chars_max == baseline.target_chars_max
    assert short.max_bubbles <= 3


@pytest.mark.parametrize(
    ("distribution", "expected"),
    [
        ({"unknown": 10.0, "multi": -1.0}, "single"),
        ({"multi": math.nan, "single": 0.2}, "single"),
        ({"multi": math.inf, "single": 0.2}, "single"),
        ({"multi": 0.5, "single": 0.5}, "single"),
    ],
)
def test_group_rhythm_accepts_only_finite_supported_values(
    distribution: dict[str, float],
    expected: str,
) -> None:
    profile = GroupExpressionProfile(
        reply_shape=GroupReplyShapeHint(rhythm_distribution=distribution),
    )

    assert resolve_reply_shape(make_turn_policy(), profile).rhythm == expected
