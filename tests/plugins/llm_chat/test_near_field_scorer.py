from __future__ import annotations

from packages.llm_chat.near_field_scorer import (
    ANSWER_SOURCE,
    RECENT_LIVE_SOURCE,
    REPEATER_SOURCE,
    recent_hint_source_label,
    select_scored_expression_candidates,
)


def test_recent_hint_source_label_prefers_recent_wording() -> None:
    assert recent_hint_source_label([{"source": RECENT_LIVE_SOURCE}]) == "当前话题可参考本群最近常接的短句"
    assert recent_hint_source_label([{"source": ANSWER_SOURCE}]) == "当前话题可参考本群常接的短句"


def test_select_scored_expression_candidates_prefers_recent_and_repeater_over_answers() -> None:
    rows = [
        {
            "text": "那确实",
            "source": ANSWER_SOURCE,
            "count": 8,
            "keywords": "明日方舟 抽卡",
            "time": 1,
            "topic_hits": 0,
        },
        {
            "text": "这也太黑了吧",
            "source": RECENT_LIVE_SOURCE,
            "count": 2,
            "keywords": "明日方舟 抽卡",
            "time": 10,
            "topic_hits": 2,
        },
        {
            "text": "你这波有点狠",
            "source": REPEATER_SOURCE,
            "count": 2,
            "keywords": "明日方舟 抽卡",
            "time": 11,
            "topic_hits": 2,
        },
    ]

    picked = select_scored_expression_candidates(
        rows,
        target_stance="complain",
        trigger_keywords=["明日方舟", "抽卡"],
        query_text="这次抽卡也太黑了吧？？？",
        limit=3,
    )

    assert picked == ["这也太黑了吧", "你这波有点狠"]


def test_select_scored_expression_candidates_dedupes_same_shape_endings() -> None:
    rows = [
        {
            "text": "这也太黑了吧",
            "source": REPEATER_SOURCE,
            "count": 3,
            "keywords": "明日方舟 抽卡",
            "time": 10,
            "topic_hits": 2,
        },
        {
            "text": "这也太离谱了吧",
            "source": REPEATER_SOURCE,
            "count": 3,
            "keywords": "明日方舟 抽卡",
            "time": 9,
            "topic_hits": 2,
        },
        {
            "text": "你这波有点狠",
            "source": REPEATER_SOURCE,
            "count": 2,
            "keywords": "明日方舟 抽卡",
            "time": 8,
            "topic_hits": 2,
        },
    ]

    picked = select_scored_expression_candidates(
        rows,
        target_stance="complain",
        trigger_keywords=["明日方舟", "抽卡"],
        query_text="这次抽卡也太黑了吧？？？",
        limit=3,
    )

    assert picked == ["这也太黑了吧", "你这波有点狠"]


def test_select_scored_expression_candidates_allows_answer_only_fallback() -> None:
    rows = [
        {
            "text": "那确实有点离谱",
            "source": ANSWER_SOURCE,
            "count": 4,
            "keywords": "明日方舟 六星",
            "time": 1,
            "topic_hits": 0,
        },
        {
            "text": "你这波有点狠",
            "source": ANSWER_SOURCE,
            "count": 3,
            "keywords": "明日方舟 抽卡",
            "time": 2,
            "topic_hits": 0,
        },
    ]

    picked = select_scored_expression_candidates(
        rows,
        target_stance="complain",
        trigger_keywords=["明日方舟", "抽卡"],
        query_text="这次抽卡也太黑了",
        limit=3,
    )

    assert picked == ["你这波有点狠", "那确实有点离谱"]


def test_select_scored_expression_candidates_prefers_more_recent_complain_when_near_field_only() -> None:
    rows = [
        {
            "text": "你这波有点狠",
            "source": RECENT_LIVE_SOURCE,
            "count": 1,
            "keywords": "明日方舟 抽卡",
            "time": 10,
            "topic_hits": 1,
        },
        {
            "text": "这波真的黑",
            "source": RECENT_LIVE_SOURCE,
            "count": 1,
            "keywords": "明日方舟 抽卡",
            "time": 20,
            "topic_hits": 1,
        },
    ]

    picked = select_scored_expression_candidates(
        rows,
        target_stance="complain",
        trigger_keywords=["明日方舟", "抽卡"],
        query_text="这次抽卡也太黑了吧？？？",
        limit=3,
    )

    assert picked == ["这波真的黑", "你这波有点狠"]


def test_select_scored_expression_candidates_filters_warm_tail_when_complain_answers_only() -> None:
    rows = [
        {
            "text": "这也太黑了吧",
            "source": ANSWER_SOURCE,
            "count": 4,
            "keywords": "明日方舟 抽卡",
            "time": 1,
            "topic_hits": 0,
        },
        {
            "text": "那确实",
            "source": ANSWER_SOURCE,
            "count": 9,
            "keywords": "明日方舟 抽卡",
            "time": 2,
            "topic_hits": 0,
        },
        {
            "text": "谢谢你呀",
            "source": ANSWER_SOURCE,
            "count": 6,
            "keywords": "明日方舟 抽卡",
            "time": 3,
            "topic_hits": 0,
        },
    ]

    picked = select_scored_expression_candidates(
        rows,
        target_stance="complain",
        trigger_keywords=["明日方舟", "抽卡"],
        query_text="这次抽卡也太黑了吧？？？",
        limit=3,
    )

    assert picked == ["这也太黑了吧"]


def test_select_scored_expression_candidates_falls_back_to_hot_rows_without_topic_match() -> None:
    rows = [
        {
            "text": "今天也行吧",
            "source": ANSWER_SOURCE,
            "count": 9,
            "keywords": "吃饭 下班",
            "time": 1,
            "topic_hits": 0,
        },
        {"text": "也不是不行", "source": ANSWER_SOURCE, "count": 7, "keywords": "夜宵", "time": 2, "topic_hits": 0},
    ]

    picked = select_scored_expression_candidates(
        rows,
        target_stance="complain",
        trigger_keywords=["明日方舟"],
        query_text="这次抽卡也太黑了",
        limit=3,
    )

    assert picked == ["今天也行吧", "也不是不行"]
