"""按受控语义标签选择表情候选。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pallas.product.llm.sticker_labels import (
    ACTION_VOCABULARY,
    EMOTION_VOCABULARY,
    TONE_VOCABULARY,
    StickerSemanticLabel,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

VISION_CLOSE_SCORE_GAP = 12.0
VISION_MIN_LABEL_CONFIDENCE = 0.6


@dataclass(frozen=True)
class StickerCandidate:
    cq_code: str
    content_hash: str


@dataclass(frozen=True)
class RankedStickerCandidate:
    candidate: StickerCandidate
    content_hash: str
    score: float
    reasons: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class StickerIntent:
    emotions: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    tones: tuple[str, ...] = ()
    usage: tuple[str, ...] = ()


def normalize_sticker_intent(intent: str | StickerIntent | None) -> StickerIntent:
    if isinstance(intent, StickerIntent):
        return intent
    values: dict[str, list[str]] = {"emotion": [], "action": [], "tone": [], "usage": []}
    for token in str(intent or "").strip().split():
        key, separator, value = token.partition(":")
        if separator and key in values and value:
            values[key].append(value)
    return StickerIntent(
        emotions=tuple(value for value in EMOTION_VOCABULARY if value in values["emotion"]),
        actions=tuple(value for value in ACTION_VOCABULARY if value in values["action"]),
        tones=tuple(value for value in TONE_VOCABULARY if value in values["tone"]),
        usage=tuple(dict.fromkeys(value.strip()[:160] for value in values["usage"] if value.strip()))[:3],
    )


def rank_sticker_candidates(
    intent: str | StickerIntent | None,
    candidates: Sequence[StickerCandidate],
    labels: Mapping[str, StickerSemanticLabel],
    recent_hashes: Collection[str],
) -> tuple[RankedStickerCandidate, ...]:
    """稳定地按标签匹配度排序，不读取图片也不调用模型。"""
    normalized = normalize_sticker_intent(intent)
    recent = {str(value) for value in recent_hashes}
    ranked: list[tuple[int, RankedStickerCandidate]] = []
    for index, candidate in enumerate(candidates):
        content_hash = str(candidate.content_hash)
        label = labels.get(content_hash)
        if content_hash in recent or (label is not None and not label.is_sticker):
            continue
        score = 0.0
        reasons: list[str] = []
        confidence = float(label.confidence) if label is not None else 0.0
        if label is None:
            reasons.append("missing_label")
        else:
            score += 10.0 * confidence
            for emotion in normalized.emotions:
                if emotion in label.emotions:
                    score += 20.0
                    reasons.append(f"emotion:{emotion}")
            for action in normalized.actions:
                if action in label.actions:
                    score += 14.0
                    reasons.append(f"action:{action}")
            for tone in normalized.tones:
                if tone in label.tones:
                    score += 6.0
                    reasons.append(f"tone:{tone}")
            for usage in normalized.usage:
                if usage in label.usage:
                    score += 12.0
                    reasons.append(f"usage:{usage}")
                if usage in label.avoid:
                    score -= 40.0
                    reasons.append(f"avoid:{usage}")
        ranked.append((
            index,
            RankedStickerCandidate(
                candidate=candidate,
                content_hash=content_hash,
                score=score,
                reasons=tuple(reasons),
                confidence=confidence,
            ),
        ))
    ordered = sorted(ranked, key=lambda pair: (-pair[1].score, -pair[1].confidence, pair[0]))
    return tuple(item for _index, item in ordered)


def should_refine_with_vision(
    ranked: Sequence[RankedStickerCandidate],
    labels: Mapping[str, StickerSemanticLabel],
) -> bool:
    """仅在标签不能明确选出高置信候选时请求在线视觉模型。"""
    if not ranked:
        return False
    if not any(item.content_hash in labels for item in ranked):
        return True
    leader = ranked[0]
    if leader.confidence < VISION_MIN_LABEL_CONFIDENCE:
        return True
    if len(ranked) > 1 and leader.score - ranked[1].score < VISION_CLOSE_SCORE_GAP:
        return True
    return False
