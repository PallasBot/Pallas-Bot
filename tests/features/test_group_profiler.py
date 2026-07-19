from __future__ import annotations

from pallas.core.foundation.db.modules import Answer, Message


def _msg(*, group_id: int, plain_text: str, ts: int, user_id: int = 1) -> Message:
    return Message.model_construct(
        group_id=group_id,
        user_id=user_id,
        bot_id=114514,
        raw_message=plain_text,
        is_plain_text=True,
        plain_text=plain_text,
        keywords=plain_text,
        time=ts,
    )


def _answer(*, group_id: int, keywords: str, message: str, count: int, ts: int) -> Answer:
    return Answer(keywords=keywords, group_id=group_id, count=count, time=ts, messages=[message])


def test_build_group_style_profile_ignores_stale_data_and_requires_enough_samples() -> None:
    from pallas.product.persona.group_profiler import build_group_style_profile

    now = 1_700_000_000
    profile = build_group_style_profile(
        group_id=100,
        messages=[
            _msg(group_id=100, plain_text="现在", ts=now - 60),
            _msg(group_id=100, plain_text="过期", ts=now - 169 * 3600),
        ],
        answers=[
            _answer(group_id=100, keywords="好", message="嗯", count=1, ts=now - 120),
            _answer(group_id=100, keywords="旧", message="老", count=1, ts=now - 169 * 3600),
        ],
        now_ts=now,
        window_hours=168,
    )

    assert profile["sample"]["message_count"] == 1
    assert profile["sample"]["answer_count"] == 1
    assert "derived" not in profile
    assert "affect_tone" in profile["raw"]


def test_build_group_style_profile_prefers_short_lively_groups() -> None:
    from pallas.product.persona.group_profiler import build_group_style_profile

    now = 1_700_000_000
    messages = [_msg(group_id=200, plain_text="草", ts=now - 60 * i, user_id=(i % 5) + 1) for i in range(30)]
    answers = [_answer(group_id=200, keywords=f"k{i % 6}", message="哈哈", count=2, ts=now - 45 * i) for i in range(8)]

    profile = build_group_style_profile(
        group_id=200,
        messages=messages,
        answers=answers,
        now_ts=now,
        window_hours=168,
    )

    assert profile["derived"]["length_pref"] == "short"
    assert profile["derived"]["reply_bias_mul"] > 1.0
    assert profile["derived"]["chaos_bias"] > 0.0
    assert "warmth_bias" in profile["derived"]
    assert "assertiveness_bias" in profile["derived"]
    assert profile["sample"]["affect_refine"]["source"] == "none"


def test_build_group_style_profile_boosts_forced_teach_weight() -> None:
    from pallas.product.persona.group_profiler import build_group_style_profile

    now = 1_700_000_000
    messages = [_msg(group_id=200, plain_text="草", ts=now - 60 * i, user_id=(i % 5) + 1) for i in range(30)]
    answers = [_answer(group_id=200, keywords=f"k{i % 6}", message="哈哈", count=2, ts=now - 45 * i) for i in range(8)]

    base = build_group_style_profile(
        group_id=200,
        messages=messages,
        answers=answers,
        now_ts=now,
        window_hours=168,
        forced_teach_weight=0.0,
    )
    boosted = build_group_style_profile(
        group_id=200,
        messages=messages,
        answers=answers,
        now_ts=now,
        window_hours=168,
        forced_teach_weight=5.0,
    )

    assert boosted["sample"]["forced_teach_weight"] == 5.0
    assert boosted["derived"]["chaos_bias"] >= base["derived"]["chaos_bias"]


def test_build_group_style_profile_prefers_long_calm_groups() -> None:
    from pallas.product.persona.group_profiler import build_group_style_profile

    now = 1_700_000_000
    long_text = "这是一条比较长而且偏叙述风格的群消息"
    messages = [
        _msg(group_id=300, plain_text=long_text + str(i), ts=now - 1800 * i, user_id=(i % 3) + 1) for i in range(30)
    ]
    answers = [
        _answer(group_id=300, keywords=f"ans{i}", message=long_text + f"回复{i}", count=1, ts=now - 1700 * i)
        for i in range(5)
    ]

    profile = build_group_style_profile(
        group_id=300,
        messages=messages,
        answers=answers,
        now_ts=now,
        window_hours=168,
    )

    assert profile["derived"]["length_pref"] == "long"
    assert profile["derived"]["reply_bias_mul"] <= 1.05
    assert profile["derived"]["chaos_bias"] <= 0.1


def test_build_group_style_profile_tracks_affect_tone() -> None:
    from pallas.product.persona.group_profiler import build_group_style_profile

    now = 1_700_000_000
    messages = [_msg(group_id=400, plain_text="谢谢辛苦收到", ts=now - 60 * i, user_id=(i % 4) + 1) for i in range(30)]
    answers = [_answer(group_id=400, keywords=f"k{i}", message="好的", count=1, ts=now - 45 * i) for i in range(8)]

    profile = build_group_style_profile(
        group_id=400,
        messages=messages,
        answers=answers,
        now_ts=now,
        window_hours=168,
    )

    tone = profile["raw"]["affect_tone"]
    assert tone["polite_msg_ratio"] > 0.0
    assert tone["civility_score"] > 0.0
    assert profile["derived"]["warmth_bias"] > 0.0
