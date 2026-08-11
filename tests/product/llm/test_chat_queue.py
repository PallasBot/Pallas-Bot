from __future__ import annotations

import pytest

from pallas.product.llm.chat_queue import (
    ChatQueueMergeResult,
    begin_chat_turn,
    clear_chat_queue_for_tests,
    finish_chat_turn,
    merge_queued_chat,
    stash_chat_during_cooldown,
    stash_pending_chat,
    take_pending_chat,
    take_pending_chat_one,
)


@pytest.fixture(autouse=True)
def _clean_chat_queue() -> None:
    clear_chat_queue_for_tests()
    yield
    clear_chat_queue_for_tests()


def test_begin_chat_turn_allows_only_one_worker_per_session() -> None:
    assert begin_chat_turn(10001, 20002, 30003)
    assert not begin_chat_turn(10001, 20002, 30003)
    finish_chat_turn(10001, 20002, 30003)
    assert begin_chat_turn(10001, 20002, 30003)


def test_stash_and_take_pending_chat_merges_in_arrival_order() -> None:
    stash_pending_chat(10001, 20002, 30003, "第一句")
    stash_pending_chat(10001, 20002, 30003, "第二句")
    assert take_pending_chat(10001, 20002, 30003) == "第一句\n第二句"
    assert take_pending_chat(10001, 20002, 30003) == ""


def test_different_sessions_do_not_share_in_flight_ownership() -> None:
    assert begin_chat_turn(10001, 20002, 30003)
    assert begin_chat_turn(10001, 20002, 30004)
    finish_chat_turn(10001, 20002, 30003)
    assert begin_chat_turn(10001, 20002, 30003)


def test_different_sessions_do_not_share_pending_text() -> None:
    stash_pending_chat(10001, 20002, 30003, "第一句")
    stash_pending_chat(10001, 20002, 30004, "另一句")
    assert take_pending_chat(10001, 20002, 30003) == "第一句"
    assert take_pending_chat(10001, 20002, 30004) == "另一句"


def test_in_flight_and_pending_keyed_by_group_id() -> None:
    assert begin_chat_turn(10001, 20002, 30003)
    assert begin_chat_turn(10001, 20003, 30003)
    stash_pending_chat(10001, 20002, 30003, "群A")
    stash_pending_chat(10001, None, 30003, "私聊")
    assert take_pending_chat(10001, 20002, 30003) == "群A"
    assert take_pending_chat(10001, None, 30003) == "私聊"


def test_stash_pending_chat_ignores_blank_text() -> None:
    stash_pending_chat(10001, 20002, 30003, "   ")
    assert take_pending_chat(10001, 20002, 30003) == ""


def test_merge_queued_chat_preserves_four_branch_contract() -> None:
    assert merge_queued_chat(10001, 20002, 30003, "现在这句") == ChatQueueMergeResult("现在这句", False)
    stash_chat_during_cooldown(10001, 20002, 30003, "冷却那句")
    assert merge_queued_chat(10001, 20002, 30003, "现在这句") == ChatQueueMergeResult("冷却那句\n现在这句", True)
    stash_chat_during_cooldown(10001, 20002, 30003, "重复")
    assert merge_queued_chat(10001, 20002, 30003, "重复") == ChatQueueMergeResult("重复", True)


def test_take_pending_chat_one_returns_single_entry_in_order() -> None:
    stash_pending_chat(10001, 20002, 30003, "第一句", message_id=11)
    stash_pending_chat(10001, 20002, 30003, "第二句", message_id=22)
    assert take_pending_chat_one(10001, 20002, 30003) == ("第一句", 11)
    assert take_pending_chat_one(10001, 20002, 30003) == ("第二句", 22)
    assert take_pending_chat_one(10001, 20002, 30003) == ("", 0)


def test_stash_pending_chat_defaults_message_id_to_zero() -> None:
    stash_pending_chat(10001, 20002, 30003, "没带 id")
    assert take_pending_chat_one(10001, 20002, 30003) == ("没带 id", 0)
