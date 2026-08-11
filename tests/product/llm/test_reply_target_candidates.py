from __future__ import annotations

from pallas.product.llm.reply_target_candidates import (
    clear_reply_target_candidates,
    list_reply_target_candidates,
    record_reply_target_candidate,
)


def test_recent_reply_target_candidates_keep_current_message_and_recent_group_context() -> None:
    clear_reply_target_candidates()
    record_reply_target_candidate(group_id=10, message_id=101, sender_id=1, text="前面那个报错了")
    record_reply_target_candidate(group_id=10, message_id=102, sender_id=2, text="我在看日志")
    record_reply_target_candidate(group_id=10, message_id=103, sender_id=3, text="这个怎么修？")

    candidates = list_reply_target_candidates(group_id=10, current_message_id=103)

    assert [item.message_id for item in candidates] == [101, 102, 103]
    assert candidates[-1].is_current is True


def test_recent_reply_target_candidates_exclude_stale_and_invalid_messages() -> None:
    clear_reply_target_candidates()
    record_reply_target_candidate(group_id=10, message_id=101, sender_id=1, text="   ")
    record_reply_target_candidate(group_id=10, message_id=0, sender_id=1, text="没有消息 id")

    assert list_reply_target_candidates(group_id=10) == []


def test_recent_reply_target_candidates_are_bounded_and_deduplicated() -> None:
    clear_reply_target_candidates()
    for index in range(1, 9):
        record_reply_target_candidate(group_id=10, message_id=100 + index, sender_id=1, text=f"消息 {index}")
    record_reply_target_candidate(group_id=10, message_id=105, sender_id=1, text="重复的消息 5")

    candidates = list_reply_target_candidates(group_id=10)

    assert [item.message_id for item in candidates] == [103, 104, 105, 106, 107, 108]
    assert candidates[0].text == "消息 3"
    assert candidates[2].text == "消息 5"


def test_recent_reply_target_candidates_truncate_long_text() -> None:
    clear_reply_target_candidates()
    record_reply_target_candidate(group_id=10, message_id=101, sender_id=1, text="长" * 300)

    candidates = list_reply_target_candidates(group_id=10)

    assert len(candidates[0].text) == 160
    assert candidates[0].text == "长" * 160
