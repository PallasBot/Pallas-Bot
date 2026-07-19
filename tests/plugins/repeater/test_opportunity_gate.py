from __future__ import annotations

from packages.repeater.opportunity_gate import should_attempt_repeater_opportunity


def test_should_attempt_repeater_opportunity_accepts_to_me() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "？",
            unique_users=1,
            recent_message_count=1,
            has_candidate_pool=False,
            candidate_pool_size=0,
            candidate_style_score=0.0,
            has_recent_back_and_forth=False,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=True,
        )
        is True
    )


def test_should_attempt_repeater_opportunity_rejects_sparse_single_user_chat() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "好耶",
            unique_users=1,
            recent_message_count=2,
            has_candidate_pool=True,
            candidate_pool_size=2,
            candidate_style_score=0.8,
            has_recent_back_and_forth=False,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is False
    )


def test_should_attempt_repeater_opportunity_rejects_short_ungrounded_message() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "草",
            unique_users=3,
            recent_message_count=5,
            has_candidate_pool=False,
            candidate_pool_size=0,
            candidate_style_score=0.0,
            has_recent_back_and_forth=True,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is False
    )


def test_should_attempt_repeater_opportunity_accepts_active_grounded_message() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "这下稳了吧",
            unique_users=3,
            recent_message_count=5,
            has_candidate_pool=True,
            candidate_pool_size=3,
            candidate_style_score=0.75,
            has_recent_back_and_forth=True,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is True
    )


def test_should_attempt_repeater_opportunity_rejects_flat_chat_without_reply_cue() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "今天确实有点热",
            unique_users=3,
            recent_message_count=5,
            has_candidate_pool=False,
            candidate_pool_size=0,
            candidate_style_score=0.0,
            has_recent_back_and_forth=False,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is False
    )


def test_should_attempt_repeater_opportunity_accepts_back_and_forth_without_candidate_pool() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "真的假的？",
            unique_users=3,
            recent_message_count=6,
            has_candidate_pool=False,
            candidate_pool_size=0,
            candidate_style_score=0.0,
            has_recent_back_and_forth=True,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is True
    )


def test_should_attempt_repeater_opportunity_rejects_when_bot_just_replied_without_strong_cue() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "今天天气不错啊",
            unique_users=3,
            recent_message_count=6,
            has_candidate_pool=True,
            candidate_pool_size=2,
            candidate_style_score=0.55,
            has_recent_back_and_forth=False,
            bot_recently_replied=True,
            reply_mode="normal",
            is_to_me=False,
        )
        is False
    )


def test_should_attempt_repeater_opportunity_accepts_cue_with_pool_even_if_bot_just_replied() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "真的假的？",
            unique_users=3,
            recent_message_count=6,
            has_candidate_pool=True,
            candidate_pool_size=2,
            candidate_style_score=0.4,
            has_recent_back_and_forth=False,
            bot_recently_replied=True,
            reply_mode="normal",
            is_to_me=False,
        )
        is True
    )


def test_should_attempt_repeater_opportunity_accepts_cue_with_pool_at_two_recent_messages() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "笑死",
            unique_users=2,
            recent_message_count=2,
            has_candidate_pool=True,
            candidate_pool_size=2,
            candidate_style_score=0.3,
            has_recent_back_and_forth=False,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is True
    )


def test_should_attempt_repeater_opportunity_ghost_accepts_weaker_but_stylish_pool() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "有点怪",
            unique_users=3,
            recent_message_count=5,
            has_candidate_pool=True,
            candidate_pool_size=1,
            candidate_style_score=0.78,
            has_recent_back_and_forth=False,
            bot_recently_replied=False,
            reply_mode="ghost",
            is_to_me=False,
        )
        is True
    )


def test_should_attempt_repeater_opportunity_god_rejects_same_weak_pool() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "有点怪",
            unique_users=3,
            recent_message_count=5,
            has_candidate_pool=True,
            candidate_pool_size=1,
            candidate_style_score=0.78,
            has_recent_back_and_forth=False,
            bot_recently_replied=False,
            reply_mode="god",
            is_to_me=False,
        )
        is False
    )


def test_should_attempt_repeater_opportunity_normal_rejects_low_style_single_candidate() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "确实",
            unique_users=3,
            recent_message_count=5,
            has_candidate_pool=True,
            candidate_pool_size=1,
            candidate_style_score=0.35,
            has_recent_back_and_forth=False,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is False
    )
