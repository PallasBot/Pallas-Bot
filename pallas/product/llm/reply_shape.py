"""Pure reply-shape policy resolution."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pallas.product.llm.inference_params import chat_reply_token_budget

if TYPE_CHECKING:
    from pallas.product.llm.turn_policy import TurnPolicy
    from pallas.product.persona.group_expression_profile import GroupExpressionProfile


@dataclass(frozen=True)
class ReplyShapePolicy:
    preferred_bubbles: int
    max_bubbles: int
    target_chars_min: int
    target_chars_max: int
    total_length_band: str
    rhythm: str
    max_output_tokens: int


def resolve_group_rhythm(group_expression: GroupExpressionProfile | None) -> str:
    if group_expression is None:
        return "single"
    distribution = group_expression.reply_shape.rhythm_distribution
    best_name = "single"
    best_weight = 0.0
    for name in ("single", "multi"):
        try:
            weight = float(distribution.get(name, 0.0))
        except (TypeError, ValueError):
            continue
        if math.isfinite(weight) and weight > best_weight:
            best_name = name
            best_weight = weight
    return best_name


def resolve_reply_shape(
    turn_policy: TurnPolicy,
    group_expression: GroupExpressionProfile | None,
) -> ReplyShapePolicy:
    if turn_policy.needs_tool:
        return ReplyShapePolicy(
            preferred_bubbles=1,
            max_bubbles=2,
            target_chars_min=8,
            target_chars_max=160,
            total_length_band="task",
            rhythm="single",
            max_output_tokens=chat_reply_token_budget("tool"),
        )
    if turn_policy.seriousness != "casual":
        return ReplyShapePolicy(
            preferred_bubbles=1,
            max_bubbles=2,
            target_chars_min=8,
            target_chars_max=80,
            total_length_band="complete",
            rhythm="single",
            max_output_tokens=chat_reply_token_budget("serious"),
        )

    shape = group_expression.reply_shape if group_expression is not None else None
    preferred_bubbles = max(1, min(3, int(shape.bubble_count_p50 or 2))) if shape else 2
    observed_max = int(shape.bubble_count_p90 or 3) if shape else 3
    max_bubbles = max(preferred_bubbles, min(5, max(1, observed_max)))
    return ReplyShapePolicy(
        preferred_bubbles=preferred_bubbles,
        max_bubbles=max_bubbles,
        target_chars_min=4,
        target_chars_max=18,
        total_length_band="short",
        rhythm=resolve_group_rhythm(group_expression),
        max_output_tokens=chat_reply_token_budget("casual"),
    )
