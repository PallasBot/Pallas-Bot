from __future__ import annotations

from types import SimpleNamespace

from pallas.core.foundation.db.modules import Message


def _msg(*, group_id: int, user_id: int, raw: str) -> Message:
    return Message.model_construct(
        group_id=group_id,
        user_id=user_id,
        bot_id=114514,
        raw_message=raw,
        is_plain_text=True,
        plain_text=raw,
        keywords=raw,
        time=1_700_000_000,
    )


def test_is_forced_repeat_teaching_requires_threshold_chain(monkeypatch) -> None:
    from packages.repeater.repeat_teach import is_forced_repeat_teaching

    monkeypatch.setattr(
        "packages.repeater.repeat_teach.repeat_ignore_user_ids",
        lambda: set(),
    )
    chat = SimpleNamespace(group_id=1, user_id=10, raw_message="草")
    prior = [_msg(group_id=1, user_id=11, raw="草"), _msg(group_id=1, user_id=12, raw="草")]
    assert is_forced_repeat_teaching(chat, prior, repeat_threshold=3) is True
    assert is_forced_repeat_teaching(chat, prior[:1], repeat_threshold=3) is False


def test_merge_forced_teach_weight_decays_and_accumulates() -> None:
    from pallas.product.persona.group_style_refresh import merge_forced_teach_weight

    prev = {"sample": {"forced_teach_weight": 2.0}}
    merged = merge_forced_teach_weight(prev, pending_events=1)
    assert merged == 2.7
