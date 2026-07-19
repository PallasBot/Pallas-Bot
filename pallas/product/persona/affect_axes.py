"""情感轴推导与分档文案。"""

from __future__ import annotations

_AffectTier = tuple[float, float, str]


def clamp_axis(value: float, *, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def derive_bluntness(
    *,
    assertiveness: float = 0.0,
    harsh_msg_ratio: float = 0.0,
    polite_msg_ratio: float = 0.0,
    punct_aggression_avg: float = 0.0,
) -> float:
    score = (
        float(assertiveness) * 0.35
        + max(0.0, float(harsh_msg_ratio)) * 0.45
        + max(0.0, float(punct_aggression_avg)) * 0.2
        - max(0.0, float(polite_msg_ratio)) * 0.35
    )
    return round(clamp_axis(score), 3)


def pick_tier_hint(value: float, tiers: tuple[_AffectTier, ...]) -> str:
    axis = float(value)
    for low, high, hint in tiers:
        if low <= axis < high:
            return hint
    return ""


_WARMTH_HINTS: tuple[_AffectTier, ...] = (
    (-1.01, -0.25, "- 态度偏冷，非必要不多接话。"),
    (-0.25, -0.08, "- 略偏克制，可少接无关碎话。"),
    (-0.08, 0.08, "- 态度中性，按群节奏自然接话。"),
    (0.08, 0.25, "- 态度偏温和，优先接住话题，少生硬拒绝。"),
    (0.25, 1.01, "- 态度很热络，积极回应与接梗。"),
)

_ASSERTIVENESS_HINTS: tuple[_AffectTier, ...] = (
    (-1.01, -0.25, "- 偏被动，少反呛，顺着群聊节奏。"),
    (-0.25, -0.08, "- 略偏收敛，顶嘴与反抛都克制。"),
    (-0.08, 0.08, "- 主张适中，可接梗但不抢戏。"),
    (0.08, 0.25, "- 可适度接梗、反抛或短促顶一句，但保持帕拉斯身份。"),
    (0.25, 1.01, "- 更敢接梗与反抛，语气可更利落。"),
)

_BLUNTNESS_HINTS: tuple[_AffectTier, ...] = (
    (-1.01, -0.25, "- 措辞偏客气，少用冲词与硬怼。"),
    (-0.25, -0.08, "- 略偏礼貌，拒绝时仍留余地。"),
    (-0.08, 0.08, "- 直率与礼貌均衡，按情境切换。"),
    (0.08, 0.25, "- 可更直接，少绕弯子。"),
    (0.25, 1.01, "- 语气偏直给，可带群常破口癖但勿越界。"),
)


def warmth_behavior_hint(warmth: float) -> str:
    return pick_tier_hint(warmth, _WARMTH_HINTS)


def assertiveness_behavior_hint(assertiveness: float) -> str:
    return pick_tier_hint(assertiveness, _ASSERTIVENESS_HINTS)


def bluntness_behavior_hint(bluntness: float) -> str:
    return pick_tier_hint(bluntness, _BLUNTNESS_HINTS)
