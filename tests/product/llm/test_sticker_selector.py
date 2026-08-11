from pallas.product.llm.sticker_labels import StickerSemanticLabel
from pallas.product.llm.sticker_selector import (
    StickerCandidate,
    rank_sticker_candidates,
    should_refine_with_vision,
)


def label(content_hash: str, **kwargs: object) -> StickerSemanticLabel:
    confidence = float(kwargs.pop("confidence", 0.95))
    return StickerSemanticLabel(
        content_hash=content_hash,
        is_sticker=True,
        confidence=confidence,
        **kwargs,
    )


def test_rank_sticker_candidates_prefers_intent_match_and_is_stable() -> None:
    happy = "a" * 64
    wave = "b" * 64
    ranked = rank_sticker_candidates(
        "emotion:开心 action:挥手",
        [StickerCandidate("[CQ:image,file=wave]", wave), StickerCandidate("[CQ:image,file=happy]", happy)],
        {
            happy: label(happy, emotions=("开心",)),
            wave: label(wave, actions=("挥手",)),
        },
        recent_hashes=(),
    )

    assert [item.content_hash for item in ranked] == [happy, wave]
    assert ranked[0].score > ranked[1].score
    assert "emotion:开心" in ranked[0].reasons


def test_rank_sticker_candidates_avoids_recent_and_non_stickers() -> None:
    preferred = "a" * 64
    recent = "b" * 64
    rejected = "c" * 64
    ranked = rank_sticker_candidates(
        "emotion:开心",
        [
            StickerCandidate("[CQ:image,file=recent]", recent),
            StickerCandidate("[CQ:image,file=rejected]", rejected),
            StickerCandidate("[CQ:image,file=preferred]", preferred),
        ],
        {
            preferred: label(preferred, emotions=("开心",)),
            recent: label(recent, emotions=("开心",)),
            rejected: StickerSemanticLabel(content_hash=rejected, is_sticker=False, confidence=0.99),
        },
        recent_hashes=(recent,),
    )

    assert [item.content_hash for item in ranked] == [preferred]


def test_non_sticker_candidates_are_hard_excluded_before_vision_refinement() -> None:
    rejected = "c" * 64
    ranked = rank_sticker_candidates(
        "emotion:开心",
        [StickerCandidate("[CQ:image,file=rejected]", rejected)],
        {rejected: StickerSemanticLabel(content_hash=rejected, is_sticker=False, confidence=0.99)},
        recent_hashes=(),
    )

    assert ranked == ()
    assert not should_refine_with_vision(ranked, {})


def test_refine_with_vision_for_close_low_confidence_or_missing_labels() -> None:
    first = "a" * 64
    second = "b" * 64
    close = rank_sticker_candidates(
        "emotion:开心",
        [StickerCandidate("a", first), StickerCandidate("b", second)],
        {first: label(first, emotions=("开心",)), second: label(second, emotions=("开心",))},
        recent_hashes=(),
    )
    low_confidence = rank_sticker_candidates(
        "emotion:开心",
        [StickerCandidate("a", first)],
        {first: label(first, emotions=("开心",), confidence=0.2)},
        recent_hashes=(),
    )
    missing = rank_sticker_candidates(
        "emotion:开心",
        [StickerCandidate("a", first)],
        {},
        recent_hashes=(),
    )

    assert should_refine_with_vision(close, {first: label(first), second: label(second)})
    assert should_refine_with_vision(low_confidence, {first: label(first, confidence=0.2)})
    assert should_refine_with_vision(missing, {})


def test_refine_with_vision_skips_clear_high_confidence_leader() -> None:
    first = "a" * 64
    second = "b" * 64
    labels = {
        first: label(first, emotions=("开心",), actions=("挥手",)),
        second: label(second, emotions=("难过",)),
    }
    ranked = rank_sticker_candidates(
        "emotion:开心 action:挥手",
        [StickerCandidate("a", first), StickerCandidate("b", second)],
        labels,
        recent_hashes=(),
    )

    assert not should_refine_with_vision(ranked, labels)
