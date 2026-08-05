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
