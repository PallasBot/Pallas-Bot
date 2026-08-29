from datetime import UTC, datetime


def test_legacy_style_profile_maps_only_deterministic_expression_fields() -> None:
    from pallas.product.persona.group_expression_profile import GroupExpressionProfile

    profile = GroupExpressionProfile.from_style_profile({
        "updated_at": 1_700_000_000,
        "sample": {"window_hours": 168, "message_count": 40, "answer_count": 8},
        "raw": {
            "avg_plain_len": 8.5,
            "p50_plain_len": 6,
            "p90_plain_len": 18,
            "msgs_per_hour_active": 4.0,
            "local_answer_ratio": 0.2,
            "repeat_chain_rate": 0.15,
        },
        "derived": {
            "length_pref": "short",
            "warmth_bias": 0.2,
            "assertiveness_bias": -0.1,
            "chaos_bias": 0.2,
        },
    })

    assert profile.updated_at == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert profile.aggregate.message_count == 40
    assert profile.aggregate.message_length.p50 == 6
    assert profile.aggregate.answer_ratio == 0.2
    assert profile.aggregate.repetition_rate == 0.15
    assert profile.reply_shape.length_pref == "short"
    dumped = profile.model_dump(mode="json")
    assert "warmth_bias" not in str(dumped)
    assert "assertiveness_bias" not in str(dumped)
    assert "chaos_bias" not in str(dumped)


def test_new_profile_round_trip_keeps_semantic_summary_without_quota_state() -> None:
    from pallas.product.persona.group_expression_profile import GroupExpressionProfile

    profile = GroupExpressionProfile.model_validate({
        "aggregate": {"sample_count": 12, "message_count": 10, "answer_count": 2},
        "examples_summary": {
            "profile_ref": "100:42:group_chat",
            "sample_count": 3,
            "direct_example_count": 1,
            "direct_pair_count": 1,
        },
        "reply_shape": {"bubble_count_p50": 2, "segment_char_length_p50": 7},
        "updated_at": "2026-08-11T00:00:00Z",
    })

    assert profile.examples_summary.profile_ref == "100:42:group_chat"
    assert profile.reply_shape.bubble_count_p50 == 2
    assert "quota" not in str(profile.model_dump(mode="json"))


def test_semantic_snapshot_updates_examples_summary_without_overriding_reply_shape() -> None:
    from pallas.product.persona.group_expression_profile import GroupExpressionProfile

    profile = GroupExpressionProfile().with_semantic_profile({
        "bot_id": 100,
        "group_id": 42,
        "scene": "group_chat",
        "sample_count": 4,
        "direct_examples": ["行"],
        "direct_pairs": [{"trigger_text": "走吗", "reply_text": "行"}],
        "rewrite_seeds": ["等等"],
        "bubble_counts": [1, 2, 2, 3],
        "segment_char_lengths": [1, 2, 4, 8],
        "rhythm_counts": {"single": 1, "multi": 3},
        "intensity_counts": {"sharp": 3, "neutral": 1},
        "form_counts": {"fragment": 2},
        "updated_at": 1_700_000_000,
        "quota_counter": 99,
    })

    assert profile.examples_summary.profile_ref == "100:42:group_chat"
    assert profile.examples_summary.direct_pair_count == 1
    assert profile.examples_summary.intensity_counts == {"sharp": 3, "neutral": 1}
    assert profile.examples_summary.form_counts == {"fragment": 2}
    # reply_shape 只由群消息（group_profiler）计算，语义快照不再覆写其分位。
    assert profile.reply_shape.bubble_count_p50 == 0
    assert profile.reply_shape.bubble_count_p90 == 0
    assert profile.reply_shape.rhythm_distribution == {}
    assert "quota" not in str(profile.model_dump(mode="json"))
