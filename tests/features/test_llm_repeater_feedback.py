from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.repeater_feedback import (
    LlmRepeaterFeedbackEntry,
    append_feedback_entry,
    build_feedback_entry,
    feedback_entries_path,
    find_feedback_entry_by_bot_message_id,
    group_feedback_bias_snapshot,
    list_group_feedback_entries,
    should_collect_llm_repeater_feedback,
)


def test_llm_repeater_feedback_defaults_enabled_bias(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.feedback_embedding_cache.schedule_feedback_trigger_backfill",
        lambda: None,
    )
    clear_llm_config_cache()
    monkeypatch.delenv("LLM_REPEATER_FEEDBACK_ENABLED", raising=False)
    monkeypatch.delenv("LLM_REPEATER_BIAS_ENABLED", raising=False)

    defaults = LlmConfig()
    assert defaults.llm_repeater_feedback_enabled is True
    assert defaults.llm_repeater_bias_enabled is True


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


def test_should_collect_llm_repeater_feedback_rejects_unknown_task() -> None:
    accepted = should_collect_llm_repeater_feedback(
        task_type="other",
        group_id=123,
        user_text="嘎嘎",
        reply_text="我赌你的枪里",
        source_tags=[],
    )

    assert accepted is False


def test_normalize_feedback_llm_route_strips_explicit_route() -> None:
    from pallas.product.llm.repeater_feedback import normalize_feedback_llm_route

    assert normalize_feedback_llm_route("") == ""
    assert normalize_feedback_llm_route("  plain_llm_chat  ") == "plain_llm_chat"


def test_build_feedback_entry_defaults_bias_enabled() -> None:
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


@pytest.mark.asyncio
async def test_long_delivered_reply_keeps_lookup_only_negative_feedback(monkeypatch, tmp_path) -> None:
    from pallas.product.llm import delivery as llm_delivery
    from pallas.product.llm.delivery import maybe_append_llm_repeater_feedback
    from pallas.product.llm.repeater_feedback import apply_llm_negative_feedback_for_bot_message

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: SimpleNamespace(llm_repeater_feedback_enabled=True),
    )
    reply = "这是一段超过现有学习长度的群聊回复。" * 8
    maybe_append_llm_repeater_feedback(
        "long-reply",
        {
            "task_type": "llm_chat",
            "bot_id": 10001,
            "group_id": 20001,
            "user_id": 30001,
            "user_text": "请详细说明",
            "scene_tier": "strong",
            "injection_snapshot": {"ambient_turns": [{"turn_id": "turn-1", "text_preview": "详细说明"}]},
        },
        reply,
        bot_message_id=40001,
    )

    found = find_feedback_entry_by_bot_message_id(bot_id=10001, group_id=20001, bot_message_id=40001)
    assert found is not None
    assert found.bot_message_id == 40001
    assert found.eligible_for_bias is False
    assert found.reply_text == reply[:120]
    assert group_feedback_bias_snapshot(group_id=20001)["count"] == 0

    result = await apply_llm_negative_feedback_for_bot_message(
        bot_id="10001",
        group_id="20001",
        bot_message_id="40001",
        actor_id="50001",
        reason="not_allowed_reply",
    )

    assert result is not None
    assert result.applied is True
    assert {item.source_id for item in result.decisions} == {"turn-1"}


def test_bot_message_lookup_uses_revision_index_and_invalidates_on_rewrite(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_feedback as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    mod.clear_group_feedback_entries_cache()
    first = mod.build_feedback_entry(
        bot_id=100,
        group_id=42,
        user_id=200,
        request_id="first",
        user_text="前句",
        reply_text="接话",
        bot_message_id=5001,
    )
    mod.append_feedback_entry(first)
    original_iter = mod._iter_feedback_entries
    scans = 0

    def counted_iter(path):
        nonlocal scans
        scans += 1
        yield from original_iter(path)

    monkeypatch.setattr(mod, "_iter_feedback_entries", counted_iter)
    assert mod.find_feedback_entry_by_bot_message_id(bot_id=100, group_id=42, bot_message_id=5001) == first
    assert mod.find_feedback_entry_by_bot_message_id(bot_id=100, group_id=42, bot_message_id=5001) == first
    assert scans == 1
    second = first.model_copy(update={"entry_id": "second", "request_id": "second", "bot_message_id": 5002})
    mod.append_feedback_entry(second)
    assert mod.find_feedback_entry_by_bot_message_id(bot_id=100, group_id=42, bot_message_id=5002) == second
    assert scans == 1
    mod._write_feedback_entries([second])
    assert mod.find_feedback_entry_by_bot_message_id(bot_id=100, group_id=42, bot_message_id=5001) is None
    assert scans == 2


def test_bot_message_lookup_falls_back_beyond_index_window_with_scope(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_feedback as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    mod.clear_group_feedback_entries_cache()
    path = mod.feedback_entries_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        mod.build_feedback_entry(
            entry_id="old",
            request_id="old",
            bot_id=100,
            group_id=42,
            user_id=200,
            user_text="前句",
            reply_text="接话",
            bot_message_id=5001,
        ).model_dump(mode="json")
    ]
    rows.extend(
        mod.build_feedback_entry(
            entry_id=f"new-{index}",
            request_id=f"new-{index}",
            bot_id=100,
            group_id=42,
            user_id=200,
            user_text="前句",
            reply_text="接话",
            bot_message_id=6000 + index,
        ).model_dump(mode="json")
        for index in range(4097)
    )
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    found = mod.find_feedback_entry_by_bot_message_id(bot_id=100, group_id=42, bot_message_id=5001)

    assert found is not None
    assert found.entry_id == "old"
    assert mod.find_feedback_entry_by_bot_message_id(bot_id=101, group_id=42, bot_message_id=5001) is None
    assert mod.find_feedback_entry_by_bot_message_id(bot_id=100, group_id=43, bot_message_id=5001) is None


def test_bot_message_lookup_missing_file_does_not_create_storage(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_feedback as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    mod.clear_group_feedback_entries_cache()

    assert mod.find_feedback_entry_by_bot_message_id(bot_id=100, group_id=42, bot_message_id=5001) is None
    assert not (tmp_path / "llm_repeater_feedback").exists()


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


def test_list_group_feedback_entries_filters_by_bot(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.repeater_feedback import append_feedback_entry, build_feedback_entry

    for bot_id in (10001, 10002):
        append_feedback_entry(
            build_feedback_entry(
                entry_id=f"entry-{bot_id}",
                request_id=f"request-{bot_id}",
                bot_id=bot_id,
                group_id=123,
                user_id=456,
                user_text="你好",
                reply_text="嗨。",
            )
        )

    assert [row.bot_id for row in list_group_feedback_entries(group_id=123, bot_id=10002)] == [10002]


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


def test_delete_feedback_entry_matches_entry_id_with_scope(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.repeater_feedback import (
        append_feedback_entry,
        build_feedback_entry,
        delete_feedback_entry,
        find_feedback_entry,
    )

    for bot_id, group_id in ((10001, 123), (10002, 456)):
        append_feedback_entry(
            build_feedback_entry(
                entry_id="shared-entry",
                request_id=f"request-{bot_id}",
                bot_id=bot_id,
                group_id=group_id,
                user_id=789,
                user_text="你好",
                reply_text="嗨。",
            )
        )

    assert delete_feedback_entry(entry_id="shared-entry", bot_id=10001, group_id=123) is True
    assert find_feedback_entry(request_id="request-10001") is None
    assert find_feedback_entry(request_id="request-10002") is not None

    remaining = find_feedback_entry(request_id="request-10002")
    assert remaining is not None
    assert (remaining.bot_id, remaining.group_id) == (10002, 456)


@pytest.mark.parametrize(
    ("action", "assertion"),
    [
        ("invalidate", lambda entry: entry.eligible_for_bias is False),
        ("restore", lambda entry: entry.eligible_for_bias is True),
        ("correct", lambda entry: entry.corrected_reply_text == "当前 scope"),
        ("clear_correction", lambda entry: entry.corrected_reply_text == ""),
        ("delete", lambda entry: entry is None),
    ],
)
def test_feedback_mutations_match_shared_id_with_exact_scope(tmp_path, monkeypatch, action, assertion) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.repeater_feedback import (
        append_feedback_entry,
        build_feedback_entry,
        clear_feedback_entry_correction,
        delete_feedback_entry,
        find_feedback_entry,
        set_feedback_entry_correction,
        set_feedback_entry_eligibility,
    )

    for bot_id, group_id in ((10001, 123), (10002, 456)):
        append_feedback_entry(
            build_feedback_entry(
                entry_id="shared-entry",
                request_id="shared-request",
                bot_id=bot_id,
                group_id=group_id,
                user_id=789,
                user_text="你好",
                reply_text="嗨。",
                corrected_reply_text="原校正" if action == "clear_correction" else "",
                corrected_at=1 if action == "clear_correction" else 0,
            )
        )

    kwargs = {"entry_id": "shared-entry", "bot_id": 10001, "group_id": 123}
    if action == "invalidate":
        updated = set_feedback_entry_eligibility(**kwargs, eligible_for_bias=False)
    elif action == "restore":
        updated = set_feedback_entry_eligibility(**kwargs, eligible_for_bias=True)
    elif action == "correct":
        updated = set_feedback_entry_correction(**kwargs, corrected_reply_text="当前 scope")
    elif action == "clear_correction":
        updated = clear_feedback_entry_correction(**kwargs)
    else:
        updated = delete_feedback_entry(**kwargs)

    assert assertion(
        updated if action != "delete" else find_feedback_entry(request_id="shared-request", bot_id=10001, group_id=123)
    )
    foreign = find_feedback_entry(request_id="shared-request", bot_id=10002, group_id=456)
    assert foreign is not None
    if action == "delete":
        assert foreign.corrected_reply_text == ""
    elif action == "correct":
        assert foreign.corrected_reply_text == ""
    elif action == "clear_correction":
        assert foreign.corrected_reply_text == "原校正"


def test_feedback_entry_mutation_reloads_inside_lock_and_preserves_concurrent_append(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_feedback as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    original = mod.build_feedback_entry(
        entry_id="original",
        request_id="original",
        bot_id=10001,
        group_id=123,
        user_id=456,
        user_text="你好",
        reply_text="嗨。",
    )
    appended = original.model_copy(update={"entry_id": "appended", "request_id": "appended"})
    mod.append_feedback_entry(original)
    mutation_waiting = threading.Event()
    append_finished = threading.Event()
    mutation_thread_id: list[int] = []

    @contextmanager
    def controlled_lock(path):
        if threading.get_ident() == mutation_thread_id[0]:
            mutation_waiting.set()
            assert append_finished.wait(timeout=1)
        yield

    monkeypatch.setattr("pallas.core.foundation.fs_lock.interprocess_file_lock", controlled_lock)
    monkeypatch.setattr(mod, "interprocess_file_lock", controlled_lock, raising=False)
    result: list[object] = []

    def mutate() -> None:
        mutation_thread_id.append(threading.get_ident())
        result.append(mod.set_feedback_entry_eligibility(entry_id="original", eligible_for_bias=False))

    thread = threading.Thread(target=mutate)
    thread.start()
    assert mutation_waiting.wait(timeout=1)
    mod.append_feedback_entry(appended)
    append_finished.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert result[0] is not None
    rows = {entry.entry_id: entry for entry in mod._load_all_feedback_entries()}
    assert rows["original"].eligible_for_bias is False
    assert rows["appended"].request_id == "appended"


def test_feedback_entry_noop_mutations_skip_write_and_cache_invalidation(tmp_path, monkeypatch) -> None:
    from pallas.core.foundation import fs_lock
    from pallas.product.llm import repeater_feedback as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    no_correction = mod.build_feedback_entry(
        entry_id="no-correction",
        request_id="no-correction",
        bot_id=10001,
        group_id=123,
        user_id=456,
        user_text="你好",
        reply_text="嗨。",
    )
    with_correction = no_correction.model_copy(
        update={
            "entry_id": "with-correction",
            "request_id": "with-correction",
            "corrected_reply_text": "改过的回复",
            "corrected_at": 1,
        }
    )
    mod.append_feedback_entry(no_correction)
    mod.append_feedback_entry(with_correction)
    atomic_writes = 0
    cache_clears = 0
    original_atomic_write = fs_lock.atomic_write_text
    original_clear_cache = mod.clear_group_feedback_entries_cache

    def spy_atomic_write(path, body):
        nonlocal atomic_writes
        atomic_writes += 1
        original_atomic_write(path, body)

    def spy_clear_cache() -> None:
        nonlocal cache_clears
        cache_clears += 1
        original_clear_cache()

    monkeypatch.setattr(fs_lock, "atomic_write_text", spy_atomic_write)
    monkeypatch.setattr(mod, "clear_group_feedback_entries_cache", spy_clear_cache)

    unchanged_eligibility = mod.set_feedback_entry_eligibility(entry_id="no-correction", eligible_for_bias=True)
    unchanged_correction = mod.clear_feedback_entry_correction(entry_id="no-correction")

    assert unchanged_eligibility is not None
    assert unchanged_eligibility.eligible_for_bias is True
    assert unchanged_correction is not None
    assert unchanged_correction.corrected_reply_text == ""
    assert atomic_writes == 0
    assert cache_clears == 0

    changed_eligibility = mod.set_feedback_entry_eligibility(entry_id="no-correction", eligible_for_bias=False)
    cleared_correction = mod.clear_feedback_entry_correction(entry_id="with-correction")

    assert changed_eligibility is not None
    assert changed_eligibility.eligible_for_bias is False
    assert cleared_correction is not None
    assert cleared_correction.corrected_reply_text == ""
    assert cleared_correction.corrected_at == 0
    assert atomic_writes == 2
    assert cache_clears == 2


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

    snap = group_feedback_bias_snapshot(bot_id=10001, group_id=123, limit=50, user_text="真棒啊")

    assert snap["matched_replies"] == ["还行吧"]


def test_group_feedback_bias_snapshot_isolates_runtime_bot(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    for bot_id, reply in ((10001, "本机回复"), (10002, "另一 Bot 回复")):
        append_feedback_entry(
            build_feedback_entry(
                bot_id=bot_id,
                group_id=123,
                user_id=456,
                request_id=f"snapshot-{bot_id}",
                user_text="你好",
                reply_text=reply,
            )
        )

    snapshot = group_feedback_bias_snapshot(bot_id=10001, group_id=123, limit=50)

    assert snapshot["top_replies"] == ["本机回复"]


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

    snap = group_feedback_bias_snapshot(
        group_id=123,
        limit=50,
        user_text="真棒啊",
        hotpath=True,
    )

    assert snap["matched_replies"] == ["还行吧"]
    assert snap["semantic_matched_replies"] == ["还行吧"]
    assert seen.get("policy") == "memory_only"
    assert snap["learning_stats"] == {}


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


def test_feedback_entry_keeps_injection_snapshot_and_find_by_message_id(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    entry = build_feedback_entry(
        request_id="request-1",
        bot_id=10001,
        group_id=20001,
        user_id=30001,
        user_text="你好",
        reply_text="鸡巴",
        bot_message_id=40001,
        injection_snapshot={"semantic_examples": [{"example_id": "sem-1", "trigger": "你好", "reply": "鸡巴"}]},
    )
    append_feedback_entry(entry)

    found = find_feedback_entry_by_bot_message_id(bot_id=10001, group_id=20001, bot_message_id=40001)
    assert found is not None
    assert found.injection_snapshot.semantic_examples[0]["example_id"] == "sem-1"


@pytest.mark.asyncio
async def test_negative_feedback_missing_entry_does_not_write_ledger(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.injection_feedback import outcomes_path
    from pallas.product.llm.repeater_feedback import apply_llm_negative_feedback_for_bot_message

    result = await apply_llm_negative_feedback_for_bot_message(
        bot_id="10001",
        group_id="20001",
        bot_message_id="30001",
        actor_id="40001",
        reason="not_allowed_reply",
    )

    assert result is None
    assert not outcomes_path().exists()


@pytest.mark.asyncio
async def test_negative_feedback_applies_once_with_scoped_audit_and_source_effects(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.injection_feedback import outcomes_path
    from pallas.product.llm.repeater_feedback import apply_llm_negative_feedback_for_bot_message

    entry = build_feedback_entry(
        entry_id="entry-negative",
        request_id="request-negative",
        bot_id=10001,
        group_id=20001,
        user_id=30001,
        user_text="你好",
        reply_text="别叫我坏名了",
        behavior_scene="banter",
        bot_message_id=40001,
        injection_snapshot={
            "expression_entries": [
                {"entry_id": "expr-20001-included", "saying": "别叫我坏名了"},
                {"entry_id": "expr-99999-foreign", "saying": "不在回复里"},
            ],
            "self_aliases": [{"alias": "坏名"}],
        },
    )
    append_feedback_entry(entry)
    expression_calls: list[tuple[list[str], str, int, str]] = []
    rejected: list[str] = []
    alias_calls: list[tuple[int, list[str]]] = []

    monkeypatch.setattr(
        "pallas.product.persona.expression_bank.record_expression_outcome",
        lambda ids, *, scene, score_delta, outcome_id: expression_calls.append((ids, scene, score_delta, outcome_id)),
    )
    monkeypatch.setattr(
        "pallas.product.persona.expression_bank.expression_scene_feedback_score",
        lambda entry_id, *, scene: -3 if entry_id == "expr-20001-included" else 0,
    )
    monkeypatch.setattr(
        "pallas.product.persona.expression_promote.resolve_expression",
        lambda entry_id, *, action, reason="": rejected.append(entry_id),
    )

    async def remove_aliases(bot_id: int, aliases: list[str]) -> None:
        alias_calls.append((bot_id, aliases))

    monkeypatch.setattr("pallas.product.persona.self_identity.remove_learned_self_aliases", remove_aliases)

    first = await apply_llm_negative_feedback_for_bot_message(
        bot_id="10001",
        group_id="20001",
        bot_message_id="40001",
        actor_id="50001",
        reason="not_allowed_reply",
    )
    duplicate = await apply_llm_negative_feedback_for_bot_message(
        bot_id="10001",
        group_id="20001",
        bot_message_id="40001",
        actor_id="50002",
        reason="admin_recall",
    )

    assert first is not None
    assert first.applied is True
    assert duplicate is not None
    assert duplicate.applied is False
    assert first.outcome_id == duplicate.outcome_id == "entry-negative:not-allowed"
    assert expression_calls == [(["expr-20001-included"], "banter", -3, "entry-negative:not-allowed")]
    assert rejected == ["expr-20001-included"]
    assert alias_calls == [(10001, ["坏名"])]
    stored = json.loads(outcomes_path().read_text(encoding="utf-8"))
    assert stored["bot_id"] == 10001
    assert stored["group_id"] == 20001
    assert stored["actor_id"] == "50001"
    assert stored["reason"] == "not_allowed_reply"


@pytest.mark.asyncio
async def test_negative_feedback_retries_pending_expression_effect_without_double_score(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.injection_feedback import outcomes_path
    from pallas.product.llm.repeater_feedback import apply_llm_negative_feedback_for_bot_message
    from pallas.product.persona.expression_bank import (
        ExpressionEntry,
        append_or_merge_expression,
        expression_scene_feedback_score,
        list_group_expressions,
    )

    expression = append_or_merge_expression(
        ExpressionEntry(
            entry_id="new",
            group_id=20001,
            occasion="banter",
            saying="这句不行",
            source="llm_success",
            channel="group",
            scene_tier="strong",
            status="shadow",
            affect_hint="",
            created_at=1,
            updated_at=1,
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            entry_id="retry-expression",
            request_id="retry-expression",
            bot_id=10001,
            group_id=20001,
            user_id=30001,
            user_text="你好",
            reply_text="这句不行",
            behavior_scene="banter",
            bot_message_id=40001,
            injection_snapshot={"expression_entries": [{"entry_id": expression.entry_id, "saying": "这句不行"}]},
        )
    )
    from pallas.product.persona import expression_promote

    original_resolve = expression_promote.resolve_expression
    attempts = 0

    def fail_once(entry_id: str, *, action: str, reason: str = "") -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("transient expression store failure")
        original_resolve(entry_id, action=action, reason=reason)

    monkeypatch.setattr(expression_promote, "resolve_expression", fail_once)

    first = await apply_llm_negative_feedback_for_bot_message(
        bot_id="10001", group_id="20001", bot_message_id="40001", actor_id="50001", reason="not_allowed_reply"
    )
    second = await apply_llm_negative_feedback_for_bot_message(
        bot_id="10001", group_id="20001", bot_message_id="40001", actor_id="50002", reason="admin_recall"
    )

    assert first is not None
    assert first.applied is True
    assert second is not None
    assert second.applied is False
    assert attempts == 2
    assert expression_scene_feedback_score(expression.entry_id, scene="banter") == -3
    assert {item.entry_id: item for item in list_group_expressions(20001)}[expression.entry_id].status == "rejected"
    stored = json.loads(outcomes_path().read_text(encoding="utf-8"))
    assert stored["effects"]["expression"]["completed"] is True


@pytest.mark.asyncio
async def test_concurrent_negative_feedback_claims_expression_effect_once(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm import repeater_feedback

    append_feedback_entry(
        build_feedback_entry(
            entry_id="concurrent-expression",
            request_id="concurrent-expression",
            bot_id=10001,
            group_id=20001,
            user_id=30001,
            user_text="你好",
            reply_text="这句不行",
            behavior_scene="banter",
            bot_message_id=40001,
            injection_snapshot={"expression_entries": [{"entry_id": "expr-20001-concurrent", "saying": "这句不行"}]},
        )
    )
    first_started = threading.Event()
    release_first = threading.Event()
    application_calls = 0

    def block_first_application(*_args) -> None:
        nonlocal application_calls
        application_calls += 1
        if application_calls == 1:
            first_started.set()
            release_first.wait()

    monkeypatch.setattr(repeater_feedback, "apply_expression_negative_feedback", block_first_application)

    first = asyncio.create_task(
        repeater_feedback.apply_llm_negative_feedback_for_bot_message(
            bot_id="10001",
            group_id="20001",
            bot_message_id="40001",
            actor_id="50001",
            reason="not_allowed_reply",
        )
    )
    await asyncio.to_thread(first_started.wait)
    second = await repeater_feedback.apply_llm_negative_feedback_for_bot_message(
        bot_id="10001",
        group_id="20001",
        bot_message_id="40001",
        actor_id="50002",
        reason="admin_recall",
    )
    release_first.set()
    first_result = await first

    assert application_calls == 1
    assert first_result is not None
    assert first_result.applied is True
    assert second is not None
    assert second.applied is False


@pytest.mark.asyncio
async def test_negative_feedback_runs_blocking_ledger_steps_in_threads(monkeypatch) -> None:
    from pallas.product.llm import injection_feedback, repeater_feedback

    entry = build_feedback_entry(
        entry_id="entry-thread",
        request_id="request-thread",
        bot_id=10001,
        group_id=20001,
        user_id=30001,
        user_text="你好",
        reply_text="不可以",
        bot_message_id=40001,
    )
    result = injection_feedback.NegativeOutcomeApplyResult(
        applied=True,
        outcome_id="entry-thread:not-allowed",
        bot_id=10001,
        group_id=20001,
        decisions=[
            injection_feedback.SourceDecision(
                kind="expression",
                source_id="expr-20001-threaded",
                score=-3,
            )
        ],
    )
    thread_calls: list[str] = []

    async def run_in_thread(function, /, *args, **kwargs):
        thread_calls.append(function.__name__)
        return function(*args, **kwargs)

    def find_entry(**_kwargs):
        return entry

    def apply_outcome(**_kwargs):
        return result

    def apply_expression(*_args) -> None:
        return None

    def claim_effect(**_kwargs) -> bool:
        return True

    def mark_effect_completed(**_kwargs) -> bool:
        return True

    def begin_effect(**_kwargs) -> bool:
        return True

    monkeypatch.setattr(repeater_feedback, "find_feedback_entry_by_bot_message_id", find_entry)
    monkeypatch.setattr(injection_feedback, "apply_negative_outcome", apply_outcome)
    monkeypatch.setattr(injection_feedback, "claim_negative_outcome_effect", claim_effect)
    monkeypatch.setattr(injection_feedback, "begin_negative_outcome_effect", begin_effect)
    monkeypatch.setattr(injection_feedback, "mark_negative_outcome_effect_completed", mark_effect_completed)
    monkeypatch.setattr(repeater_feedback, "apply_expression_negative_feedback", apply_expression)
    monkeypatch.setattr(repeater_feedback.asyncio, "to_thread", run_in_thread)

    applied = await repeater_feedback.apply_llm_negative_feedback_for_bot_message(
        bot_id="10001",
        group_id="20001",
        bot_message_id="40001",
        actor_id="50001",
        reason="not_allowed_reply",
    )

    assert applied == result
    assert thread_calls == [
        "find_entry",
        "apply_outcome",
        "claim_effect",
        "begin_effect",
        "apply_expression",
        "mark_effect_completed",
    ]


@pytest.mark.asyncio
async def test_undo_after_effect_claim_prevents_expression_application(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm import injection_feedback, repeater_feedback

    entry = build_feedback_entry(
        entry_id="entry-undo-race",
        request_id="request-undo-race",
        bot_id=10001,
        group_id=20001,
        user_id=30001,
        user_text="你好",
        reply_text="这句不行",
        bot_message_id=40001,
    )
    result = injection_feedback.apply_negative_outcome(
        outcome_id="entry-undo-race:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="这句不行",
        injection_snapshot={"expression_entries": [{"entry_id": "expr-20001-race", "saying": "这句不行"}]},
        now=1,
    )
    applied_calls = 0
    completed_calls = 0
    original_claim = injection_feedback.claim_negative_outcome_effect

    def claim_then_undo(**kwargs):
        lease_id = original_claim(**kwargs)
        assert lease_id
        assert injection_feedback.undo_negative_outcome(
            outcome_id=kwargs["outcome_id"], bot_id=kwargs["bot_id"], group_id=kwargs["group_id"], now=2
        )
        return lease_id

    def apply_expression(*_args) -> None:
        nonlocal applied_calls
        applied_calls += 1

    def mark_completed(**_kwargs) -> bool:
        nonlocal completed_calls
        completed_calls += 1
        return True

    monkeypatch.setattr(injection_feedback, "claim_negative_outcome_effect", claim_then_undo)
    monkeypatch.setattr(repeater_feedback, "apply_expression_negative_feedback", apply_expression)
    monkeypatch.setattr(injection_feedback, "mark_negative_outcome_effect_completed", mark_completed)

    await repeater_feedback.apply_negative_feedback_source_decisions(entry, result)

    assert applied_calls == 0
    assert completed_calls == 0
    assert (
        original_claim(
            outcome_id=result.outcome_id, bot_id=result.bot_id, group_id=result.group_id, kind="expression", now=3
        )
        is None
    )


@pytest.mark.asyncio
async def test_negative_feedback_rejects_only_expression_in_snapshot(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.repeater_feedback import apply_llm_negative_feedback_for_bot_message
    from pallas.product.persona.expression_bank import (
        ExpressionEntry,
        append_or_merge_expression,
        expression_scene_feedback_score,
        list_group_expressions,
    )

    def make_expression(saying: str) -> ExpressionEntry:
        return ExpressionEntry(
            entry_id="new",
            group_id=20001,
            occasion="banter",
            saying=saying,
            source="llm_success",
            channel="group",
            scene_tier="strong",
            status="shadow",
            affect_hint="",
            created_at=1,
            updated_at=1,
        )

    included = append_or_merge_expression(make_expression("这句不行"))
    unrelated = append_or_merge_expression(make_expression("这句没进快照"))
    append_feedback_entry(
        build_feedback_entry(
            entry_id="entry-expression",
            request_id="request-expression",
            bot_id=10001,
            group_id=20001,
            user_id=30001,
            user_text="你好",
            reply_text="这句不行",
            behavior_scene="banter",
            bot_message_id=40001,
            injection_snapshot={"expression_entries": [{"entry_id": included.entry_id, "saying": "这句不行"}]},
        )
    )

    result = await apply_llm_negative_feedback_for_bot_message(
        bot_id="10001",
        group_id="20001",
        bot_message_id="40001",
        actor_id="50001",
        reason="not_allowed_reply",
    )

    assert result is not None
    assert result.applied is True
    assert expression_scene_feedback_score(included.entry_id, scene="banter") == -3
    entries = {item.entry_id: item for item in list_group_expressions(20001)}
    assert entries[included.entry_id].status == "rejected"
    assert entries[unrelated.entry_id].status == "shadow"


def test_feedback_retention_noop_when_nothing_expired(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_feedback as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    now = int(time.time())
    for idx in range(3):
        mod.append_feedback_entry(
            mod.build_feedback_entry(
                entry_id=f"fresh-{idx}",
                request_id=f"fresh-{idx}",
                bot_id=10001,
                group_id=123,
                user_id=456 + idx,
                user_text="你好",
                reply_text="嗨。",
                created_at=now - 60,
            )
        )

    report = mod.compact_feedback_entries(retention_days=7)

    assert report == {"archived": 0, "retained": 3, "total": 3}
    assert not mod.feedback_archive_path().exists()
    lines = list(mod._iter_feedback_entries(mod.feedback_entries_path()))
    assert len(lines) == 3


def test_feedback_retention_archives_unprotected_old_entries(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_feedback as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    now = int(time.time())
    mod.append_feedback_entry(
        mod.build_feedback_entry(
            entry_id="old-plain",
            request_id="old-plain",
            bot_id=10001,
            group_id=123,
            user_id=456,
            user_text="你好",
            reply_text="嗨。",
            created_at=now - 10 * 86400,
        )
    )
    mod.append_feedback_entry(
        mod.build_feedback_entry(
            entry_id="old-strong",
            request_id="old-strong",
            bot_id=10001,
            group_id=123,
            user_id=457,
            user_text="你好",
            reply_text="嗨。",
            created_at=now - 10 * 86400,
            scene_tier="strong",
        )
    )

    report = mod.compact_feedback_entries(retention_days=7)

    assert report == {"archived": 1, "retained": 1, "total": 2}
    archive_lines = list(mod._iter_feedback_entries(mod.feedback_archive_path()))
    assert [item.request_id for item in archive_lines] == ["old-plain"]
    remaining = list(mod._iter_feedback_entries(mod.feedback_entries_path()))
    assert [item.request_id for item in remaining] == ["old-strong"]


def test_feedback_retention_protects_corrected_ineligible_and_strong(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_feedback as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    now = int(time.time())
    old = now - 10 * 86400

    mod.append_feedback_entry(
        mod.build_feedback_entry(
            entry_id="old-corrected",
            request_id="old-corrected",
            bot_id=10001,
            group_id=123,
            user_id=456,
            user_text="你好",
            reply_text="嗨。",
            created_at=old,
            corrected_reply_text="改过了",
            corrected_at=old + 1,
        )
    )
    mod.append_feedback_entry(
        mod.build_feedback_entry(
            entry_id="old-ineligible",
            request_id="old-ineligible",
            bot_id=10001,
            group_id=123,
            user_id=458,
            user_text="你好",
            reply_text="嗨。",
            created_at=old,
            eligible_for_bias=False,
        )
    )
    mod.append_feedback_entry(
        mod.build_feedback_entry(
            entry_id="old-strong",
            request_id="old-strong",
            bot_id=10001,
            group_id=123,
            user_id=459,
            user_text="你好",
            reply_text="嗨。",
            created_at=old,
            scene_tier="strong",
        )
    )
    mod.append_feedback_entry(
        mod.build_feedback_entry(
            entry_id="old-plain",
            request_id="old-plain",
            bot_id=10001,
            group_id=123,
            user_id=460,
            user_text="你好",
            reply_text="嗨。",
            created_at=old,
        )
    )

    report = mod.compact_feedback_entries(retention_days=7)

    assert report == {"archived": 1, "retained": 3, "total": 4}
    retained = {item.request_id for item in mod._iter_feedback_entries(mod.feedback_entries_path())}
    assert retained == {
        "old-corrected",
        "old-ineligible",
        "old-strong",
    }
    archived = {item.request_id for item in mod._iter_feedback_entries(mod.feedback_archive_path())}
    assert archived == {"old-plain"}
