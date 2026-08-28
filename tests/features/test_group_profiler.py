from __future__ import annotations

import pytest

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

    assert profile["aggregate"]["message_count"] == 1
    assert profile["aggregate"]["answer_count"] == 1
    assert profile["reply_shape"]["length_pref"] == "any"
    assert "derived" not in profile


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

    assert profile["reply_shape"]["length_pref"] == "short"
    assert profile["aggregate"]["messages_per_active_hour"] > 0
    assert profile["aggregate"]["repetition_rate"] > 0.0
    assert "warmth_bias" not in str(profile)


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

    assert boosted["aggregate"]["forced_teach_weight"] == 5.0
    assert boosted["aggregate"]["repetition_rate"] == base["aggregate"]["repetition_rate"]


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

    assert profile["reply_shape"]["length_pref"] == "long"
    assert profile["aggregate"]["message_length"]["p50"] >= 20


def test_build_group_style_profile_does_not_write_account_persona_fields() -> None:
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

    assert "warmth" not in str(profile)
    assert "assertiveness" not in str(profile)
    assert "chaos" not in str(profile)


@pytest.mark.asyncio
async def test_recent_profile_uses_distinct_message_repository_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.persona import group_profiler

    messages = [
        _msg(group_id=500, plain_text="短消息", ts=1_700_000_000 - index, user_id=index + 1) for index in range(30)
    ]
    answers = [
        _answer(group_id=500, keywords=f"k{index}", message="回复", count=1, ts=1_700_000_000 - index)
        for index in range(5)
    ]
    calls: list[tuple[int, int, int]] = []

    class Repo:
        async def find_recent_distinct_in_group(
            self,
            group_id: int,
            *,
            before_time: int,
            since_time: int,
            limit: int,
        ):
            calls.append((group_id, limit, since_time))
            return messages

        async def find_recent_in_group(self, *_args, **_kwargs):
            raise AssertionError("should use the distinct repository query")

    class ContextRepo:
        async def list_answers_for_group_since(self, group_id: int, cutoff_time: int):
            return answers

    monkeypatch.setattr(group_profiler, "is_peer_bot", lambda _user_id: False)
    profile = await group_profiler.build_group_style_profile_from_recent_repos(
        group_id=500,
        message_repo=Repo(),
        context_repo=ContextRepo(),
        now_ts=1_700_000_000,
    )

    assert calls == [(500, 256, 1_700_000_000 - 168 * 3600)]
    assert profile["aggregate"]["message_count"] == 30
    assert profile["reply_shape"]["length_pref"] == "short"


def test_reply_shape_quantiles_sort_bubble_counts() -> None:
    from pallas.product.persona.group_profiler import build_group_style_profile

    now = 1_700_000_000
    messages = [
        _msg(group_id=600, plain_text="第一段\n第二段", ts=now - index, user_id=index + 1) for index in range(15)
    ] + [_msg(group_id=600, plain_text="单段", ts=now - index - 15, user_id=index + 16) for index in range(15)]
    answers = [
        _answer(group_id=600, keywords=f"k{index}", message="回复", count=1, ts=now - index) for index in range(5)
    ]

    profile = build_group_style_profile(
        group_id=600,
        messages=messages,
        answers=answers,
        now_ts=now,
    )

    assert profile["reply_shape"]["bubble_count_p50"] == 1
    assert profile["reply_shape"]["bubble_count_p90"] == 2
