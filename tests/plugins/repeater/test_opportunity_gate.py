from __future__ import annotations

from packages.repeater.opportunity_gate import (
    build_opportunity_trace_payload,
    decide_llm_attempt,
    passes_repeater_hard_bars,
    resolve_scene_tier,
    should_attempt_repeater_opportunity,
)


def test_should_attempt_repeater_opportunity_rejects_bystander_at_other() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "[CQ:at,qq=1001] 今晚开黑",
            unique_users=3,
            recent_message_count=6,
            has_candidate_pool=True,
            candidate_pool_size=3,
            candidate_style_score=0.9,
            has_recent_back_and_forth=True,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
            bot_id=2002,
        )
        is False
    )

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


def test_should_attempt_repeater_opportunity_rejects_emoji_noise_even_with_pool() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "🤔",
            unique_users=4,
            recent_message_count=8,
            has_candidate_pool=True,
            candidate_pool_size=3,
            candidate_style_score=0.9,
            has_recent_back_and_forth=True,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is False
    )


def test_should_attempt_repeater_opportunity_rejects_mid_score_without_cue() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "拉满了",
            unique_users=4,
            recent_message_count=8,
            has_candidate_pool=True,
            candidate_pool_size=3,
            candidate_style_score=0.4,
            has_recent_back_and_forth=True,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is False
    )


def test_should_attempt_repeater_opportunity_rejects_promo_link() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "⚡️不用下载点击即玩⚡️：https://www.bilibili.com/toy/Dagou-Tap/index.html",
            unique_users=4,
            recent_message_count=8,
            has_candidate_pool=True,
            candidate_pool_size=2,
            candidate_style_score=0.9,
            has_recent_back_and_forth=True,
            bot_recently_replied=False,
            reply_mode="normal",
            is_to_me=False,
        )
        is False
    )


def test_resolve_scene_tier_cue_with_pool() -> None:
    assert (
        resolve_scene_tier(
            "真的假的？",
            candidate_pool_size=2,
            has_candidate_pool=True,
            has_recent_back_and_forth=False,
            is_to_me=False,
        )
        == "strong"
    )


def test_resolve_scene_tier_cue_without_pool_is_weak() -> None:
    assert (
        resolve_scene_tier(
            "真的假的？",
            candidate_pool_size=2,
            has_candidate_pool=False,
            has_recent_back_and_forth=False,
            is_to_me=False,
        )
        == "weak"
    )


def test_resolve_scene_tier_back_and_forth_with_pool() -> None:
    assert (
        resolve_scene_tier(
            "今天确实有点热",
            candidate_pool_size=0,
            has_candidate_pool=True,
            has_recent_back_and_forth=True,
            is_to_me=False,
        )
        == "strong"
    )


def test_resolve_scene_tier_to_me() -> None:
    assert (
        resolve_scene_tier(
            "好耶",
            candidate_pool_size=0,
            has_candidate_pool=False,
            has_recent_back_and_forth=False,
            is_to_me=True,
        )
        == "strong"
    )


def test_resolve_scene_tier_weak_otherwise() -> None:
    assert (
        resolve_scene_tier(
            "今天确实有点热",
            candidate_pool_size=1,
            has_candidate_pool=True,
            has_recent_back_and_forth=False,
            is_to_me=False,
        )
        == "weak"
    )


def test_hard_bars_still_block_spam_even_if_strong_signals() -> None:
    assert (
        passes_repeater_hard_bars(
            "⚡️不用下载点击即玩⚡️：https://www.bilibili.com/toy/Dagou-Tap/index.html",
            has_candidate_pool=True,
            candidate_pool_size=3,
            has_recent_back_and_forth=True,
            bot_recently_replied=False,
        )
        is False
    )


def test_strong_tier_relaxes_soft_gate_when_hard_bars_pass() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "离谱？",
            unique_users=2,
            recent_message_count=2,
            has_candidate_pool=True,
            candidate_pool_size=3,
            candidate_style_score=0.0,
            has_recent_back_and_forth=False,
            bot_recently_replied=True,
            scene_tier="strong",
        )
        is True
    )


def test_strong_tier_rejects_single_user_chat() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "离谱？",
            unique_users=1,
            recent_message_count=2,
            has_candidate_pool=True,
            candidate_pool_size=3,
            candidate_style_score=0.0,
            has_recent_back_and_forth=False,
            bot_recently_replied=False,
            scene_tier="strong",
        )
        is False
    )


def test_strong_tier_rejects_single_recent_message() -> None:
    assert (
        should_attempt_repeater_opportunity(
            "离谱？",
            unique_users=2,
            recent_message_count=1,
            has_candidate_pool=True,
            candidate_pool_size=3,
            candidate_style_score=0.0,
            has_recent_back_and_forth=False,
            bot_recently_replied=False,
            scene_tier="strong",
        )
        is False
    )


def test_build_opportunity_trace_payload_includes_scene_tier() -> None:
    payload = build_opportunity_trace_payload(
        "离谱？",
        unique_users=2,
        recent_message_count=2,
        has_candidate_pool=True,
        candidate_pool_size=3,
        candidate_style_score=0.0,
        has_recent_back_and_forth=False,
        bot_recently_replied=False,
        accepted=True,
    )

    assert payload["scene_tier"] == "strong"


def test_decide_llm_attempt_rejects_strong_scene_at_zero_rate() -> None:
    attempted, _roll, skip_reason = decide_llm_attempt(
        scene_tier="strong",
        opportunity_accepted=True,
        strong_attempt_rate=0,
    )

    assert attempted is False
    assert skip_reason == "rate"


def test_decide_llm_attempt_accepts_weak_scene_without_roll() -> None:
    assert decide_llm_attempt(
        scene_tier="weak",
        opportunity_accepted=True,
        strong_attempt_rate=0,
    ) == (True, None, None)


def test_decide_llm_attempt_rejects_closed_opportunity_without_roll() -> None:
    assert decide_llm_attempt(
        scene_tier="strong",
        opportunity_accepted=False,
        strong_attempt_rate=1,
    ) == (False, None, "opportunity_rejected")


def test_decide_llm_attempt_uses_injected_rng_for_strong_scene() -> None:
    assert decide_llm_attempt(
        scene_tier="strong",
        opportunity_accepted=True,
        strong_attempt_rate=0.55,
        rng=lambda: 0.54,
    ) == (True, 0.54, None)
    assert decide_llm_attempt(
        scene_tier="strong",
        opportunity_accepted=True,
        strong_attempt_rate=0.55,
        rng=lambda: 0.55,
    ) == (False, 0.55, "rate")
