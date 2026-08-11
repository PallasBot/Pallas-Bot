from __future__ import annotations

import math

import pytest

from pallas.product.llm.inference_params import chat_reply_token_budget
from pallas.product.llm.reply_shape import resolve_reply_shape
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

    assert 1 <= policy.preferred_bubbles <= 2
    assert policy.max_bubbles <= 3
    assert (policy.target_chars_min, policy.target_chars_max) == (4, 18)
    assert policy.total_length_band == "short"
    assert policy.max_output_tokens == chat_reply_token_budget("casual")


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
    assert policy.max_bubbles == 3
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
