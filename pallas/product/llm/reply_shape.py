"""Pure reply-shape policy resolution."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pallas.product.llm.inference_params import chat_reply_token_budget

# 无本群统计时用的默认段长（真人语料段长中位数，约 6 字）
_DEFAULT_SEGMENT_CHAR_LENGTH_P50 = 6

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


def resolve_reply_hard_cap(
    scene_cap: int,
    *,
    preferred_bubbles: int = 1,
    bubble_count_p50: int = 0,
    segment_char_length_p50: int = 0,
    min_cap: int = 16,
) -> int:
    """按「段数 × 段中位字长 + 余量」推导回复硬上限（字符数），再 clamp 到场景 cap 内。

    本群没有真人统计（segment_char_length_p50 为 0）时，用真人语料中位段作默认段长。
    返回值为正即投入使用。
    """
    if scene_cap <= 0:
        return 0
    cap = int(scene_cap)
    segment_p50 = int(segment_char_length_p50) or _DEFAULT_SEGMENT_CHAR_LENGTH_P50
    if bubble_count_p50:
        bubble_count = max(1, min(3, int(bubble_count_p50)))
    else:
        bubble_count = max(1, min(3, int(preferred_bubbles)))
    derived = segment_p50 * bubble_count + 12
    cap = min(cap, max(min_cap, derived))
    return cap


def resolve_short_reply_split_decision(
    *,
    band: str,
    randomize_enabled: bool,
    keep_rate: float,
    rng: random.Random | None = None,
) -> bool:
    """短回复 band 下是否保留单段不拆（shape 阶段决策，delivery 只执行拆分）。"""
    if band != "short":
        return False
    if not randomize_enabled:
        return False
    rate = max(0.0, min(1.0, float(keep_rate)))
    if rate <= 0:
        return False
    dice = rng if rng is not None else random
    return dice.random() < rate


def resolve_reply_shape(
    turn_policy: TurnPolicy,
    group_expression: GroupExpressionProfile | None,
    *,
    rng: random.Random | None = None,
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

    dice = rng if rng is not None else random
    shape = group_expression.reply_shape if group_expression is not None else None
    preferred_bubbles = dice.choice([1, 2, 3]) if shape is None else max(1, min(3, int(shape.bubble_count_p50 or 2)))
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
