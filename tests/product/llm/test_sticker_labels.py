from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from pallas.product.llm.sticker_labels import (
    ACTION_VOCABULARY,
    EMOTION_VOCABULARY,
    TONE_VOCABULARY,
    StickerSemanticLabel,
    content_hash_for_bytes,
    needs_relabel,
)


def test_content_hash_is_based_only_on_original_bytes() -> None:
    payload = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\x00\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00;"

    assert content_hash_for_bytes(payload) == hashlib.sha256(payload).hexdigest()
    assert content_hash_for_bytes(payload) == content_hash_for_bytes(bytes(payload))
    assert content_hash_for_bytes(payload) != content_hash_for_bytes(payload + b"second-gif-frame")


def test_label_normalizes_controlled_arrays_and_validates_hash() -> None:
    label = StickerSemanticLabel(
        content_hash="a" * 64,
        is_sticker=True,
        emotions=(EMOTION_VOCABULARY[-1], "VLM-free-form", EMOTION_VOCABULARY[0], EMOTION_VOCABULARY[-1]),
        actions=(ACTION_VOCABULARY[-1], ACTION_VOCABULARY[0], "unknown"),
        tones=(TONE_VOCABULARY[-1], TONE_VOCABULARY[0], "unknown"),
        intensity=2,
        usage=("  适合回应朋友  ", "", "适合回应朋友"),
        avoid=("不要在严肃场合使用",),
        caption="  一只挥手的小猫  ",
        confidence=0.8,
        model="vision-test",
        prompt_version=2,
        labeled_at=1,
    )

    assert label.emotions == (EMOTION_VOCABULARY[0], EMOTION_VOCABULARY[-1])
    assert label.actions == (ACTION_VOCABULARY[0], ACTION_VOCABULARY[-1])
    assert label.tones == (TONE_VOCABULARY[0], TONE_VOCABULARY[-1])
    assert label.usage == ("适合回应朋友",)
    assert label.caption == "一只挥手的小猫"

    with pytest.raises(ValidationError):
        StickerSemanticLabel(content_hash="A" * 64, is_sticker=False)


def test_label_treats_a_string_as_one_candidate_and_enforces_limits() -> None:
    label = StickerSemanticLabel(
        content_hash="e" * 64,
        is_sticker=True,
        emotions="开心",
        actions="not-an-action",
        usage="  适合聊天  ",
        avoid=["  不要刷屏  ", "不要刷屏", "", "第三条", "第四条"],
    )

    assert label.emotions == ("开心",)
    assert label.actions == ()
    assert label.usage == ("适合聊天",)
    assert label.avoid == ("不要刷屏", "第三条", "第四条")


def test_label_rejects_truthy_non_iterable_label_values() -> None:
    with pytest.raises(ValidationError):
        StickerSemanticLabel(content_hash="f" * 64, is_sticker=True, emotions=1)

    with pytest.raises(ValidationError):
        StickerSemanticLabel(content_hash="f" * 64, is_sticker=True, usage=True)


def test_negative_label_is_cacheable_and_relabel_policy_is_explicit() -> None:
    negative = StickerSemanticLabel(content_hash="b" * 64, is_sticker=False, confidence=0.99, prompt_version=3)
    low_confidence = negative.model_copy(update={"confidence": 0.4})
    old_prompt = negative.model_copy(update={"prompt_version": 2})

    assert not needs_relabel(negative, prompt_version=3, min_confidence=0.6)
    assert needs_relabel(None, prompt_version=3, min_confidence=0.6)
    assert needs_relabel(low_confidence, prompt_version=3, min_confidence=0.6)
    assert needs_relabel(old_prompt, prompt_version=3, min_confidence=0.6)
    assert not needs_relabel(negative.model_copy(update={"confidence": 0.6}), prompt_version=3, min_confidence=0.6)
