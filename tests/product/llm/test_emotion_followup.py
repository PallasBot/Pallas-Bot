from __future__ import annotations

from pallas.product.llm.sticker_followup import should_attach_repeater_image


def test_emotion_followup_accepts_model_requested_sticker() -> None:
    task = {
        "task_type": "llm_chat",
        "speak_trigger": "to_me",
    }

    assert should_attach_repeater_image(task, "我听到了。", '{"reply":"我听到了。","sticker":"send"}')


def test_emotion_followup_rejects_model_sticker_none() -> None:
    task = {
        "task_type": "llm_chat",
        "speak_trigger": "to_me",
    }

    assert not should_attach_repeater_image(task, "谢拉格的领袖。", '{"reply":"谢拉格的领袖。","sticker":"none"}')


def test_emotion_followup_rejects_plain_text_reply() -> None:
    task = {
        "task_type": "llm_chat",
        "speak_trigger": "to_me",
    }

    assert not should_attach_repeater_image(task, "怎么了？", "怎么了？")


def test_emotion_followup_requires_a_delivered_text_reply() -> None:
    task = {
        "task_type": "llm_chat",
        "speak_trigger": "mention",
    }

    assert not should_attach_repeater_image(task, "", '{"reply":"","sticker":"send"}')


def test_sticker_followup_cooldown_and_recent_image_deduplication() -> None:
    from pallas.product.llm.sticker_followup import (
        note_repeater_image_sent,
        reset_repeater_image_followup_state_for_tests,
        should_send_repeater_image,
    )

    reset_repeater_image_followup_state_for_tests()
    assert should_send_repeater_image(42, "[CQ:image,file=a.image]", cooldown_sec=60, now=100.0)

    note_repeater_image_sent(42, "[CQ:image,file=a.image]", now=100.0)

    assert not should_send_repeater_image(42, "[CQ:image,file=b.image]", cooldown_sec=60, now=120.0)
    assert not should_send_repeater_image(42, "[CQ:image,file=a.image]", cooldown_sec=0, now=200.0)
    assert should_send_repeater_image(42, "[CQ:image,file=b.image]", cooldown_sec=60, now=200.0)
