from __future__ import annotations

import time

from pallas.product.llm.feedback_learning import (
    compute_penalized_replies,
    feedback_bias_multiplier_for_text,
    feedback_entry_age_weight,
    find_semantic_matched_replies,
    find_trigger_matched_replies,
    scene_match_weight,
    weighted_reply_counter,
)
from pallas.product.llm.repeater_feedback import build_feedback_entry


def test_feedback_entry_age_weight_decays_over_time() -> None:
    now = 1_700_000_000
    fresh = feedback_entry_age_weight(created_at=now - 3600, now=now)
    old = feedback_entry_age_weight(created_at=now - 60 * 86400, now=now)
    assert fresh > old
    assert feedback_entry_age_weight(created_at=now - 120 * 86400, now=now) == 0.0


def test_scene_match_weight_prefers_same_scene() -> None:
    assert scene_match_weight(entry_scene="banter", active_scene="banter") == 1.0
    assert scene_match_weight(entry_scene="venting", active_scene="banter") < 1.0


def test_compute_penalized_replies_from_repeated_bad_samples() -> None:
    rows = [
        build_feedback_entry(
            bot_id=1,
            group_id=123,
            user_id=1,
            request_id="bad-1",
            user_text="你好",
            reply_text="因为一般来说这样",
            eligible_for_bias=False,
        ),
        build_feedback_entry(
            bot_id=1,
            group_id=123,
            user_id=2,
            request_id="bad-2",
            user_text="在吗",
            reply_text="因为一般来说这样",
            eligible_for_bias=False,
        ),
    ]
    assert compute_penalized_replies(rows) == ["因为一般来说这样"]


def test_weighted_reply_counter_respects_scene() -> None:
    rows = [
        build_feedback_entry(
            bot_id=1,
            group_id=123,
            user_id=1,
            request_id="a",
            user_text="你真棒",
            reply_text="还行",
            behavior_scene="banter",
            created_at=int(time.time()),
        ),
        build_feedback_entry(
            bot_id=1,
            group_id=123,
            user_id=2,
            request_id="b",
            user_text="好烦",
            reply_text="抱抱",
            behavior_scene="venting",
            created_at=int(time.time()),
        ),
    ]
    banter_counter = weighted_reply_counter(rows, active_scene="banter")
    assert banter_counter.most_common(1)[0][0] == "还行"


def test_find_trigger_matched_replies() -> None:
    rows = [
        build_feedback_entry(
            bot_id=1,
            group_id=123,
            user_id=1,
            request_id="m1",
            user_text="牛牛真棒",
            reply_text="还行吧",
        )
    ]
    matched = find_trigger_matched_replies(rows=rows, user_text="牛牛真棒")
    assert matched == ["还行吧"]


def test_feedback_bias_multiplier_applies_penalty() -> None:
    mult = feedback_bias_multiplier_for_text(
        "因为一般来说",
        feedback_snapshot={
            "count": 3,
            "top_replies": [],
            "matched_replies": [],
            "semantic_matched_replies": [],
            "penalized_replies": ["因为一般来说"],
        },
    )
    assert mult == 0.45


def test_find_semantic_matched_replies_uses_embeddings(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.config.resolve_llm_vector_retrieve",
        lambda: "hybrid",
    )

    rows = [
        build_feedback_entry(
            bot_id=1,
            group_id=123,
            user_id=1,
            request_id="s1",
            user_text="你怎么又来了",
            reply_text="别闹",
        )
    ]

    def fake_fetch(texts, **kwargs):
        assert texts[0] == "又来了"
        return [[1.0, 0.0], [0.95, 0.05]]

    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.fetch_embeddings_sync",
        fake_fetch,
    )
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_score.embedding_relevance_score",
        lambda _q, _c: 88,
    )

    matched = find_semantic_matched_replies(rows=rows, user_text="又来了")
    assert matched == ["别闹"]
