from __future__ import annotations

from pallas.core.foundation.db.modules import Answer, Context
from pallas.product.corpus.merge import merge_contexts


def test_merge_contexts_none_extra():
    base = Context.model_construct(
        keywords="a b",
        time=10,
        trigger_count=2,
        answers=[Answer(keywords="c", group_id=1, count=3, time=5, messages=["c"])],
        ban=[],
        clear_time=0,
    )
    assert merge_contexts(base, None) is base


def test_merge_contexts_none_base():
    extra = Context.model_construct(
        keywords="a b",
        time=10,
        trigger_count=1,
        answers=[Answer(keywords="d", group_id=0, count=2, time=4, messages=["d"])],
        ban=[],
        clear_time=0,
    )
    merged = merge_contexts(None, extra)
    assert merged is not None
    assert merged.keywords == "a b"
    assert len(merged.answers) == 1
    assert merged.answers[0].keywords == "d"


def test_merge_local_first_skips_duplicate_answer_keys():
    base = Context.model_construct(
        keywords="k",
        time=1,
        trigger_count=1,
        answers=[Answer(keywords="x", group_id=100, count=5, time=1, messages=["a"])],
        ban=[],
        clear_time=0,
    )
    extra = Context.model_construct(
        keywords="k",
        time=2,
        trigger_count=3,
        answers=[
            Answer(keywords="x", group_id=100, count=9, time=2, messages=["b"]),
            Answer(keywords="y", group_id=0, count=1, time=2, messages=["y"]),
        ],
        ban=[],
        clear_time=0,
    )
    merged = merge_contexts(base, extra, strategy="local_first")
    assert merged is not None
    assert merged.trigger_count == 4
    by_kw = {a.keywords: a for a in merged.answers}
    assert by_kw["x"].count == 5
    assert by_kw["x"].messages == ["a"]
    assert by_kw["y"].count == 1


def test_merge_counts_adds_duplicate_answer_keys():
    base = Context.model_construct(
        keywords="k",
        time=1,
        trigger_count=1,
        answers=[Answer(keywords="x", group_id=100, count=5, time=1, messages=["a"])],
        ban=[],
        clear_time=0,
    )
    extra = Context.model_construct(
        keywords="k",
        time=3,
        trigger_count=2,
        answers=[Answer(keywords="x", group_id=100, count=4, time=3, messages=["b"])],
        ban=[],
        clear_time=0,
    )
    merged = merge_contexts(base, extra, strategy="merge_counts")
    assert merged is not None
    assert len(merged.answers) == 1
    assert merged.answers[0].count == 9
    assert merged.answers[0].time == 3
    assert merged.answers[0].messages == ["a", "b"]
