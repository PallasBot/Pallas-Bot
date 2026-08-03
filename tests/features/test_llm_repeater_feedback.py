from __future__ import annotations

from types import SimpleNamespace

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.repeater_feedback import (
    LlmRepeaterFeedbackEntry,
    append_feedback_entry,
    build_feedback_entry,
    feedback_entries_path,
    group_feedback_bias_snapshot,
    list_group_feedback_entries,
    should_collect_llm_repeater_feedback,
)


def test_llm_repeater_feedback_defaults_enabled_bias_writeback(monkeypatch) -> None:
    clear_llm_config_cache()
    monkeypatch.delenv("LLM_REPEATER_FEEDBACK_ENABLED", raising=False)
    monkeypatch.delenv("LLM_REPEATER_BIAS_ENABLED", raising=False)
    monkeypatch.delenv("LLM_REPEATER_WRITEBACK_ENABLED", raising=False)

    defaults = LlmConfig()
    assert defaults.llm_repeater_feedback_enabled is True
    assert defaults.llm_repeater_bias_enabled is True
    assert defaults.llm_repeater_writeback_enabled is True


def test_should_collect_llm_repeater_feedback_accepts_short_group_reply() -> None:
    accepted = should_collect_llm_repeater_feedback(
        task_type="llm_chat",
        group_id=123,
        user_text="你又来这套",
        reply_text="少来。",
        source_tags=[],
    )

    assert accepted is True


def test_should_collect_llm_repeater_feedback_rejects_long_explanatory_reply() -> None:
    accepted = should_collect_llm_repeater_feedback(
        task_type="llm_chat",
        group_id=123,
        user_text="银灰是谁",
        reply_text="银灰是《明日方舟》中的六星近卫干员，通常被视为谢拉格领袖，拥有很强的爆发能力。",
        source_tags=[],
    )

    assert accepted is False


def test_should_collect_llm_repeater_feedback_accepts_repeater_polish_lite() -> None:
    accepted = should_collect_llm_repeater_feedback(
        task_type="repeater_polish_lite",
        group_id=123,
        user_text="嘎嘎",
        reply_text="我赌你的枪里",
        source_tags=[],
    )

    assert accepted is True


def test_should_collect_llm_repeater_feedback_uses_fallback_when_trigger_missing() -> None:
    accepted = should_collect_llm_repeater_feedback(
        task_type="repeater_select",
        group_id=123,
        user_text="",
        reply_text="摸摸",
        source_tags=[],
        fallback_text="候选句",
    )

    assert accepted is True


def test_resolve_feedback_llm_route_maps_repeater_task() -> None:
    from pallas.product.llm.repeater_feedback import resolve_feedback_llm_route

    assert resolve_feedback_llm_route(task_type="repeater_polish_lite", llm_route="") == "corpus_polish_lite"
    assert resolve_feedback_llm_route(task_type="llm_chat", llm_route="plain_llm_chat") == "plain_llm_chat"


def test_build_feedback_entry_defaults_writeback_false() -> None:
    entry = build_feedback_entry(
        bot_id=10001,
        group_id=123,
        user_id=456,
        request_id="req-1",
        user_text="你又来这套",
        reply_text="少来。",
    )

    assert isinstance(entry, LlmRepeaterFeedbackEntry)
    assert entry.entry_id == "req-1"
    assert entry.eligible_for_bias is True
    assert entry.eligible_for_writeback is False


def test_maybe_append_feedback_marks_writeback_eligible_only_for_strong_scene(monkeypatch) -> None:
    from pallas.product.llm import delivery as llm_delivery
    from pallas.product.llm.delivery import maybe_append_llm_repeater_feedback

    appended = []
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: SimpleNamespace(llm_repeater_feedback_enabled=True),
    )
    monkeypatch.setattr(
        "pallas.product.llm.repeater_feedback.append_feedback_entry",
        appended.append,
    )
    task = {
        "task_type": "llm_chat",
        "bot_id": 10001,
        "group_id": 123,
        "user_id": 456,
        "user_text": "你又来这套",
    }

    maybe_append_llm_repeater_feedback("req-strong", {**task, "scene_tier": "strong"}, "少来。")
    maybe_append_llm_repeater_feedback("req-weak", {**task, "scene_tier": "weak"}, "少来。")

    assert [entry.eligible_for_writeback for entry in appended] == [True, False]


def test_build_feedback_entry_keeps_scene_tier() -> None:
    entry = build_feedback_entry(
        bot_id=10001,
        group_id=123,
        user_id=456,
        request_id="req-scene-tier",
        user_text="你又来这套",
        reply_text="少来。",
        scene_tier=" strong ",
    )

    assert entry.scene_tier == "strong"


def test_list_group_feedback_entries_roundtrips_scene_tier(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-scene-tier-roundtrip",
            user_text="你又来这套",
            reply_text="少来。",
            scene_tier="strong",
        )
    )

    rows = list_group_feedback_entries(group_id=123)

    assert [row.scene_tier for row in rows] == ["strong"]


def test_group_feedback_bias_snapshot_empty_when_no_entries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    snap = group_feedback_bias_snapshot(group_id=123, limit=50)

    assert snap["count"] == 0
    assert snap["top_replies"] == []


def test_group_feedback_bias_snapshot_aggregates_recent_unique_bias_entries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-1",
            user_text="你又来这套",
            reply_text="少来。",
            behavior_scene="banter",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=457,
            request_id="req-2",
            user_text="你继续说",
            reply_text="少来。",
            behavior_scene="banter",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=458,
            request_id="req-3",
            user_text="你先别急",
            reply_text="行吧。",
            behavior_scene="venting",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=459,
            request_id="req-4",
            user_text="别学这个",
            reply_text="这条不算。",
            behavior_scene="banter",
            eligible_for_bias=False,
        )
    )

    snap = group_feedback_bias_snapshot(group_id=123, limit=50)

    assert snap["count"] == 3
    assert snap["top_replies"] == ["少来。", "行吧。"]
    assert snap["scenes"] == ["banter", "venting"]


def test_group_feedback_bias_snapshot_skips_bad_lines(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-1",
            user_text="你又来这套",
            reply_text="少来。",
            behavior_scene="banter",
        )
    )
    path = feedback_entries_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{bad json}\n")
        handle.write('{"request_id":"broken"}\n')
        handle.write('{"entry_id":"req-x"')
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=457,
            request_id="req-2",
            user_text="你先别急",
            reply_text="行吧。",
            behavior_scene="venting",
        )
    )

    rows = list_group_feedback_entries(group_id=123, limit=50)
    snap = group_feedback_bias_snapshot(group_id=123, limit=50)

    assert [row.request_id for row in rows] == ["req-1", "req-2"]
    assert snap["count"] == 2
    assert snap["top_replies"] == ["少来。", "行吧。"]


def test_list_group_feedback_entries_dedupes_recent_request_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-1",
            user_text="你又来这套",
            reply_text="少来。",
            behavior_scene="banter",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-1",
            user_text="你又来这套",
            reply_text="少来。",
            behavior_scene="banter",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=457,
            request_id="req-2",
            user_text="你先别急",
            reply_text="行吧。",
            behavior_scene="venting",
        )
    )

    rows = list_group_feedback_entries(group_id=123, limit=50)
    snap = group_feedback_bias_snapshot(group_id=123, limit=50)

    assert [row.request_id for row in rows] == ["req-1", "req-2"]
    assert snap["count"] == 2
    assert snap["top_replies"] == ["少来。", "行吧。"]


def test_list_group_feedback_entries_dedupes_same_request_id_with_different_entry_id(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_feedback_entry(
        build_feedback_entry(
            entry_id="entry-a",
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-1",
            user_text="你又来这套",
            reply_text="少来。",
            behavior_scene="banter",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            entry_id="entry-b",
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-1",
            user_text="你又来这套",
            reply_text="少来。",
            behavior_scene="banter",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            entry_id="entry-c",
            bot_id=10001,
            group_id=123,
            user_id=457,
            request_id="req-2",
            user_text="你先别急",
            reply_text="行吧。",
            behavior_scene="venting",
        )
    )

    rows = list_group_feedback_entries(group_id=123, limit=50)
    snap = group_feedback_bias_snapshot(group_id=123, limit=50)

    assert [row.entry_id for row in rows] == ["entry-b", "entry-c"]
    assert [row.request_id for row in rows] == ["req-1", "req-2"]
    assert snap["count"] == 2


def test_feedback_manage_invalidate_restore_and_delete(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.repeater_feedback import (
        append_feedback_entry,
        build_feedback_entry,
        delete_feedback_entry,
        find_feedback_entry,
        list_feedback_entries_for_session,
        set_feedback_entry_eligibility,
    )

    append_feedback_entry(
        build_feedback_entry(
            entry_id="req-manage-1",
            request_id="req-manage-1",
            bot_id=10001,
            group_id=123,
            user_id=456,
            user_text="你好",
            reply_text="嗨。",
        )
    )

    updated = set_feedback_entry_eligibility(request_id="req-manage-1", eligible_for_bias=False)
    assert updated is not None
    assert updated.eligible_for_bias is False

    restored = set_feedback_entry_eligibility(entry_id="req-manage-1", eligible_for_bias=True)
    assert restored is not None
    assert restored.eligible_for_bias is True

    session_rows = list_feedback_entries_for_session(bot_id=10001, group_id=123, user_id=456, limit=10)
    assert len(session_rows) == 1
    assert session_rows[0].reply_text == "嗨。"

    assert delete_feedback_entry(request_id="req-manage-1") is True
    assert find_feedback_entry(request_id="req-manage-1") is None


def test_set_feedback_entry_correction_updates_and_creates(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.repeater_feedback import (
        append_feedback_entry,
        build_feedback_entry,
        clear_feedback_entry_correction,
        find_feedback_entry,
        set_feedback_entry_correction,
    )

    append_feedback_entry(
        build_feedback_entry(
            entry_id="req-corr-1",
            request_id="req-corr-1",
            bot_id=10001,
            group_id=123,
            user_id=456,
            user_text="你好",
            reply_text="嗨。",
        )
    )

    updated = set_feedback_entry_correction(
        request_id="req-corr-1",
        corrected_reply_text="你好呀，在呢",
    )
    assert updated is not None
    assert updated.corrected_reply_text == "你好呀，在呢"
    assert updated.eligible_for_bias is True

    created = set_feedback_entry_correction(
        request_id="req-corr-new",
        corrected_reply_text="收到",
        create_fields={
            "bot_id": 10001,
            "group_id": 123,
            "user_id": 456,
            "user_text": "在吗",
            "reply_text": "在的",
        },
    )
    assert created is not None
    assert created.request_id == "req-corr-new"
    assert created.corrected_reply_text == "收到"

    cleared = clear_feedback_entry_correction(request_id="req-corr-1")
    assert cleared is not None
    assert cleared.corrected_reply_text == ""
    assert find_feedback_entry(request_id="req-corr-new") is not None


def test_group_feedback_bias_snapshot_matched_replies_for_trigger(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-match-1",
            user_text="牛牛真棒啊",
            reply_text="还行吧",
        )
    )

    snap = group_feedback_bias_snapshot(group_id=123, limit=50, user_text="真棒啊")

    assert snap["matched_replies"] == ["还行吧"]


def test_group_feedback_bias_snapshot_hotpath_skips_heavy_stats(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-hot-1",
            user_text="牛牛真棒啊",
            reply_text="还行吧",
        )
    )

    seen: dict[str, str] = {}

    def fake_semantic(*, remote_policy: str = "full", **kwargs):
        seen["policy"] = remote_policy
        return ["还行吧"]

    def boom(*_a, **_k):
        raise AssertionError("hotpath must not compute learning/promotion stats")

    monkeypatch.setattr(
        "pallas.product.llm.feedback_learning.find_semantic_matched_replies",
        fake_semantic,
    )
    monkeypatch.setattr(
        "pallas.product.llm.feedback_learning.summarize_learning_effectiveness",
        boom,
    )
    monkeypatch.setattr(
        "pallas.product.llm.promotion_candidates.count_pending_promotion_candidates",
        boom,
    )

    snap = group_feedback_bias_snapshot(
        group_id=123,
        limit=50,
        user_text="真棒啊",
        hotpath=True,
    )

    assert snap["matched_replies"] == ["还行吧"]
    assert snap["semantic_matched_replies"] == ["还行吧"]
    assert seen.get("policy") == "query_only"
    assert snap["learning_stats"] == {}
    assert snap["promotion_candidate_count"] == 0


def test_list_group_feedback_entries_uses_short_ttl_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=55,
            user_id=1,
            request_id="cache-1",
            user_text="hi",
            reply_text="yo",
        )
    )
    first = list_group_feedback_entries(group_id=55, limit=10)
    assert len(first) == 1

    calls = {"n": 0}
    real_iter = __import__(
        "pallas.product.llm.repeater_feedback", fromlist=["_iter_feedback_entries"]
    )._iter_feedback_entries

    def counting_iter(path):
        calls["n"] += 1
        yield from real_iter(path)

    monkeypatch.setattr(
        "pallas.product.llm.repeater_feedback._iter_feedback_entries",
        counting_iter,
    )
    second = list_group_feedback_entries(group_id=55, limit=10)
    assert second[0].reply_text == "yo"
    assert calls["n"] == 0


def test_list_group_feedback_entries_updates_loaded_group_without_rescanning_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "pallas.product.llm.feedback_embedding_cache.prefetch_trigger_embedding",
        lambda _text: None,
    )
    monkeypatch.setattr(
        "pallas.product.llm.promotion_candidates.note_feedback_entry_for_promotion",
        lambda _entry: None,
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=55,
            user_id=1,
            request_id="index-1",
            user_text="hi",
            reply_text="first",
        )
    )

    calls = {"n": 0}
    real_iter = __import__(
        "pallas.product.llm.repeater_feedback", fromlist=["_iter_feedback_entries"]
    )._iter_feedback_entries

    def counting_iter(path):
        calls["n"] += 1
        yield from real_iter(path)

    monkeypatch.setattr(
        "pallas.product.llm.repeater_feedback._iter_feedback_entries",
        counting_iter,
    )

    assert [item.reply_text for item in list_group_feedback_entries(group_id=55, limit=10)] == ["first"]

    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=55,
            user_id=2,
            request_id="index-2",
            user_text="again",
            reply_text="second",
        )
    )

    assert [item.reply_text for item in list_group_feedback_entries(group_id=55, limit=10)] == [
        "first",
        "second",
    ]
    assert calls["n"] == 1


def test_should_collect_llm_repeater_feedback_rejects_attack_or_plugin_reply() -> None:
    for reply in ("我操你妈。", "匹配失败，积分不足18点", "[CQ:image,file=x]"):
        assert not should_collect_llm_repeater_feedback(
            task_type="llm_chat",
            group_id=123,
            user_text="测试",
            reply_text=reply,
            source_tags=[],
        )
