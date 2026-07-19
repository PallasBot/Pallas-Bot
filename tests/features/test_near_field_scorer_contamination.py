from pallas.product.llm.near_field_scorer import ANSWER_SOURCE, select_scored_expression_candidates


def test_select_scored_expression_candidates_skips_contaminated_rows(monkeypatch) -> None:
    from pallas.product.llm.config import LlmConfig

    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_corpus_learn_guard_enabled=True),
    )
    rows = [
        {
            "text": "希望每个庆典都能顺利",
            "count": 9,
            "keywords": "明日方舟 抽卡",
            "source": ANSWER_SOURCE,
            "time": 0,
            "topic_hits": 0,
        },
        {
            "text": "这也太黑了吧",
            "count": 4,
            "keywords": "明日方舟 抽卡",
            "source": ANSWER_SOURCE,
            "time": 0,
            "topic_hits": 0,
        },
    ]
    out = select_scored_expression_candidates(
        rows,
        target_stance="complain",
        trigger_keywords=["明日方舟", "抽卡"],
        query_text="这次抽卡也太黑了",
        limit=3,
        reference_min_len=2,
        reference_min_cjk=2,
    )
    assert out == ["这也太黑了吧"]
