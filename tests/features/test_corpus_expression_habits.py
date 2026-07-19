from __future__ import annotations

from pallas.product.persona.corpus_expression_habits import (
    infer_expression_affect_stance,
    pick_affect_aligned_corpus_expression_candidates,
    pick_corpus_expression_candidates,
    pick_topical_corpus_expression_candidates,
)


def test_pick_corpus_expression_candidates_prefers_short_popular_distinct_lines() -> None:
    candidates = pick_corpus_expression_candidates(
        [
            {"text": "行啊", "count": 6},
            {"text": "也不是不行", "count": 5},
            {"text": "行啊", "count": 3},
            {"text": "这个事情我们需要从多个角度完整分析一下", "count": 20},
            {"text": "那确实", "count": 4},
        ],
        limit=3,
    )

    assert candidates == ["行啊", "也不是不行", "那确实"]


def test_pick_corpus_expression_candidates_skips_low_info_and_cq() -> None:
    candidates = pick_corpus_expression_candidates(
        [
            {"text": "？", "count": 9},
            {"text": "[CQ:image,file=x.png]", "count": 8},
            {"text": "草", "count": 7},
            {"text": "来都来了", "count": 6},
        ],
        limit=3,
    )

    assert candidates == ["草", "来都来了"]


def test_pick_topical_corpus_expression_candidates_prefers_keyword_overlap() -> None:
    candidates = pick_topical_corpus_expression_candidates(
        [
            {"text": "那确实", "count": 4, "keywords": "明日方舟 六星"},
            {"text": "行啊", "count": 8, "keywords": "吃饭 下班"},
            {"text": "你这波有点狠", "count": 3, "keywords": "明日方舟 抽卡"},
            {"text": "也不是不行", "count": 6, "keywords": "吃饭 夜宵"},
        ],
        trigger_keywords=["明日方舟", "抽卡"],
        limit=3,
    )

    assert candidates == ["那确实", "你这波有点狠"]


def test_pick_topical_corpus_expression_candidates_returns_empty_without_trigger_keywords() -> None:
    candidates = pick_topical_corpus_expression_candidates(
        [
            {"text": "那确实", "count": 4, "keywords": "明日方舟 六星"},
            {"text": "行啊", "count": 8, "keywords": "吃饭 下班"},
        ],
        trigger_keywords=[],
        limit=3,
    )

    assert candidates == []


def test_infer_expression_affect_stance_distinguishes_common_reaction_shapes() -> None:
    assert infer_expression_affect_stance("这也太离谱了吧？？？") == "complain"
    assert infer_expression_affect_stance("谢谢你呀") == "warm"
    assert infer_expression_affect_stance("那确实") == "echo"


def test_pick_affect_aligned_corpus_expression_candidates_prefers_same_stance() -> None:
    candidates = pick_affect_aligned_corpus_expression_candidates(
        [
            {"text": "这也太黑了吧", "count": 5, "keywords": "明日方舟 抽卡"},
            {"text": "那确实", "count": 8, "keywords": "明日方舟 抽卡"},
            {"text": "谢谢你呀", "count": 6, "keywords": "明日方舟 抽卡"},
        ],
        trigger_keywords=["明日方舟", "抽卡"],
        target_stance="complain",
        limit=3,
    )

    assert candidates == ["这也太黑了吧"]
