import json
import threading
from contextlib import contextmanager

from pallas.product.llm.injection_feedback import (
    apply_negative_outcome,
    begin_negative_outcome_effect,
    claim_negative_outcome_effect,
    effective_source_score,
    filter_ambient_turns,
    list_injection_governance,
    mark_negative_outcome_effect_completed,
    outcomes_path,
    release_negative_outcome_effect_claim,
    undo_negative_outcome,
    undo_negative_outcome_status,
)


def test_expired_effect_claim_is_reclaimed_and_old_lease_cannot_mutate_it(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="expired-effect",
        bot_id=10001,
        group_id=20001,
        reply_text="不合适的句子",
        injection_snapshot={"expression_entries": [{"entry_id": "expr-20001-a", "saying": "不合适的句子"}]},
        now=1,
    )
    path = outcomes_path()
    row = json.loads(path.read_text(encoding="utf-8"))
    row["effects"] = {"expression": {"state": "claimed"}}
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    new_lease = claim_negative_outcome_effect(
        outcome_id="expired-effect", bot_id=10001, group_id=20001, kind="expression", now=302
    )

    assert new_lease
    assert not mark_negative_outcome_effect_completed(
        outcome_id="expired-effect", bot_id=10001, group_id=20001, kind="expression", lease_id="old-lease"
    )
    assert not release_negative_outcome_effect_claim(
        outcome_id="expired-effect", bot_id=10001, group_id=20001, kind="expression", lease_id="old-lease"
    )
    assert begin_negative_outcome_effect(
        outcome_id="expired-effect", bot_id=10001, group_id=20001, kind="expression", lease_id=new_lease
    )
    assert mark_negative_outcome_effect_completed(
        outcome_id="expired-effect", bot_id=10001, group_id=20001, kind="expression", lease_id=new_lease
    )


def test_parallel_effect_claims_remain_exclusive(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="parallel-effect",
        bot_id=10001,
        group_id=20001,
        reply_text="不合适的句子",
        injection_snapshot={"expression_entries": [{"entry_id": "expr-20001-a", "saying": "不合适的句子"}]},
        now=1,
    )
    barrier = threading.Barrier(2)
    claims: list[str | None] = []

    def claim() -> None:
        barrier.wait()
        claims.append(
            claim_negative_outcome_effect(
                outcome_id="parallel-effect", bot_id=10001, group_id=20001, kind="expression", now=2
            )
        )

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    assert all(not thread.is_alive() for thread in threads)
    assert sum(bool(claim) for claim in claims) == 1


def test_undo_cancels_effect_leases_and_never_allows_them_to_reapply(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="undo-effect",
        bot_id=10001,
        group_id=20001,
        reply_text="不合适的句子",
        injection_snapshot={"expression_entries": [{"entry_id": "expr-20001-a", "saying": "不合适的句子"}]},
        now=1,
    )
    lease_id = claim_negative_outcome_effect(
        outcome_id="undo-effect", bot_id=10001, group_id=20001, kind="expression", now=2
    )

    assert lease_id
    assert undo_negative_outcome(outcome_id="undo-effect", bot_id=10001, group_id=20001, now=3)
    assert not mark_negative_outcome_effect_completed(
        outcome_id="undo-effect", bot_id=10001, group_id=20001, kind="expression", lease_id=lease_id
    )
    assert not release_negative_outcome_effect_claim(
        outcome_id="undo-effect", bot_id=10001, group_id=20001, kind="expression", lease_id=lease_id
    )
    assert (
        claim_negative_outcome_effect(outcome_id="undo-effect", bot_id=10001, group_id=20001, kind="expression", now=4)
        is None
    )
    row = json.loads(outcomes_path().read_text(encoding="utf-8"))
    assert row["effects"]["expression"]["state"] == "cancelled"


def test_undo_before_effect_claim_ignores_missing_effect_state(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="undo-before-claim",
        bot_id=10001,
        group_id=20001,
        reply_text="不合适的句子",
        injection_snapshot={"expression_entries": [{"entry_id": "expr-20001-a", "saying": "不合适的句子"}]},
        now=1,
    )
    path = outcomes_path()
    row = json.loads(path.read_text(encoding="utf-8"))
    row["effects"] = {}
    row["undo"] = True
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    assert (
        claim_negative_outcome_effect(
            outcome_id="undo-before-claim", bot_id=10001, group_id=20001, kind="expression", now=2
        )
        is None
    )


def test_negative_outcome_is_idempotent_and_filters_matched_ambient(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    snapshot = {
        "ambient_turns": [{"turn_id": "turn-1", "text_preview": "鸡巴又来了"}],
        "expression_entries": [],
        "semantic_examples": [],
        "memory_entries": [],
        "self_aliases": [],
    }
    first = apply_negative_outcome(
        outcome_id="entry-1:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提鸡巴",
        injection_snapshot=snapshot,
        now=1_000,
    )
    again = apply_negative_outcome(
        outcome_id="entry-1:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提鸡巴",
        injection_snapshot=snapshot,
        now=1_000,
    )

    assert first.applied is True
    assert again.applied is False
    assert filter_ambient_turns(10001, 20001, [{"content": "鸡巴又来了"}]) == []
    assert effective_source_score(10001, 20001, "ambient", "turn-1", now=1_000) < 0


def test_scores_decay_with_thirty_day_half_life(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="entry-2:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="不合适的句子",
        injection_snapshot={"memory_entries": [{"entry_id": "mem-1", "text_preview": "不合适的句子"}]},
        now=0,
    )

    assert effective_source_score(10001, 20001, "memory", "mem-1", now=30 * 86400) == -0.5


def test_every_injected_source_scores_even_without_match(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    result = apply_negative_outcome(
        outcome_id="all-sources:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="这回复不行",
        injection_snapshot={
            "ambient_turns": [{"turn_id": "a1", "text_preview": "完全无关的话"}],
            "expression_entries": [{"entry_id": "e1", "saying": "完全无关"}],
            "semantic_examples": [{"example_id": "s1", "trigger": "无关", "reply": "无关"}],
            "memory_entries": [{"entry_id": "m1", "text_preview": "无关"}],
        },
        now=100,
    )

    assert {d.kind for d in result.decisions} == {"ambient", "expression", "semantic", "memory"}
    assert effective_source_score(10001, 20001, "ambient", "a1", now=100) == -1.0
    assert effective_source_score(10001, 20001, "expression", "e1", now=100) == -3.0
    assert effective_source_score(10001, 20001, "semantic", "s1", now=100) == -2.0
    assert effective_source_score(10001, 20001, "memory", "m1", now=100) == -1.0


def test_knowledge_and_style_profile_are_audit_only(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    result = apply_negative_outcome(
        outcome_id="audit-1:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="不合适",
        injection_snapshot={
            "knowledge_chunks": [{"source_id": "src-1", "chunk_id": "chunk-1", "score": 9}],
            "style_profile": {"version": 1, "aggregate_only": True},
        },
        now=20,
    )

    assert result.applied is True
    knowledge = next(d for d in result.decisions if d.kind == "knowledge")
    style = next(d for d in result.decisions if d.kind == "style_profile")
    assert knowledge.audit_only is True
    assert knowledge.score == 0
    assert style.audit_only is True
    assert style.score == 0
    assert effective_source_score(10001, 20001, "knowledge", "chunk-1", now=20) == 0.0


def test_self_alias_high_confidence_hit_sets_remove_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    result = apply_negative_outcome(
        outcome_id="alias-1:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别叫我鸡巴了",
        injection_snapshot={"self_aliases": [{"alias": "鸡巴", "origin": "learned"}]},
        now=50,
    )

    alias_decisions = [d for d in result.decisions if d.kind == "self_alias"]
    assert len(alias_decisions) == 1
    assert alias_decisions[0].remove_alias is True
    assert alias_decisions[0].confidence == "high"


def test_function_word_and_single_char_overlap_never_blacklist(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="fn-1:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="不可以这样的",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-f", "text_preview": "这样的回复可以吗"}]},
        now=40,
    )
    apply_negative_outcome(
        outcome_id="single-1:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提了",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-s", "text_preview": "大家别说了"}]},
        now=90,
    )

    assert filter_ambient_turns(10001, 20001, [{"content": "这样的回复可以吗"}]) == [{"content": "这样的回复可以吗"}]
    assert filter_ambient_turns(10001, 20001, [{"content": "大家别说了"}]) == [{"content": "大家别说了"}]
    assert effective_source_score(10001, 20001, "ambient", "turn-f", now=40) == -1.0


def test_governance_is_scoped_to_bot_and_group(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="scope-1:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提鸡巴",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-1", "text_preview": "鸡巴又来了"}]},
        now=60,
    )

    assert filter_ambient_turns(10001, 20002, [{"content": "鸡巴又来了"}]) == [{"content": "鸡巴又来了"}]
    assert filter_ambient_turns(10002, 20001, [{"content": "鸡巴又来了"}]) == [{"content": "鸡巴又来了"}]
    assert filter_ambient_turns(10001, 20001, [{"content": "鸡巴又来了"}]) == []
    assert effective_source_score(10001, 20002, "ambient", "turn-1", now=60) == 0.0


def test_undo_removes_outcome_from_scores_and_blacklist(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="undo-1:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="不合适的句子",
        injection_snapshot={"memory_entries": [{"entry_id": "mem-1", "text_preview": "不合适的句子"}]},
        now=0,
    )
    apply_negative_outcome(
        outcome_id="undo-2:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提鸡巴",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-1", "text_preview": "鸡巴又来了"}]},
        now=0,
    )

    assert effective_source_score(10001, 20001, "memory", "mem-1", now=5) == -1.0
    assert filter_ambient_turns(10001, 20001, [{"content": "鸡巴又来了"}]) == []
    assert undo_negative_outcome(outcome_id="undo-1:not-allowed", bot_id=10001, group_id=20001, now=5) is True
    assert undo_negative_outcome(outcome_id="undo-2:not-allowed", bot_id=10001, group_id=20001, now=5) is True
    assert effective_source_score(10001, 20001, "memory", "mem-1", now=5) == 0.0
    assert filter_ambient_turns(10001, 20001, [{"content": "鸡巴又来了"}]) == [{"content": "鸡巴又来了"}]


def test_undo_is_idempotent_and_unknown_outcome_returns_false(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="undo-3:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提鸡巴",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-1", "text_preview": "鸡巴又来了"}]},
        now=0,
    )

    assert undo_negative_outcome(outcome_id="undo-3:not-allowed", bot_id=10001, group_id=20001, now=1) is True
    assert undo_negative_outcome(outcome_id="undo-3:not-allowed", bot_id=10001, group_id=20001, now=2) is True
    assert undo_negative_outcome(outcome_id="missing:not-allowed", bot_id=10001, group_id=20001, now=2) is False


def test_missing_or_corrupt_ledger_fails_open(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    assert filter_ambient_turns(10001, 20001, [{"content": "鸡巴又来了"}]) == [{"content": "鸡巴又来了"}]
    assert effective_source_score(10001, 20001, "memory", "mem-1", now=70) == 0.0
    assert undo_negative_outcome(outcome_id="x", bot_id=10001, group_id=20001, now=70) is False

    path = outcomes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json\n\xff\xfe garbage\n", encoding="utf-8", errors="replace")

    assert filter_ambient_turns(10001, 20001, [{"content": "鸡巴又来了"}]) == [{"content": "鸡巴又来了"}]
    assert effective_source_score(10001, 20001, "memory", "mem-1", now=70) == 0.0
    assert list_injection_governance(bot_id=10001, group_id=20001)["outcomes"] == []


def test_empty_ledger_governance_read_and_missing_undo_do_not_create_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    ledger = tmp_path / "llm_repeater_feedback" / "injection_governance" / "outcomes.jsonl"

    assert list_injection_governance(bot_id=10001, group_id=20001)["outcomes"] == []
    assert undo_negative_outcome_status(outcome_id="missing", bot_id=10001, group_id=20001) == "missing"
    assert not ledger.exists()
    assert not ledger.with_suffix(".jsonl.lock").exists()
    assert not ledger.parent.exists()
    assert not ledger.parent.parent.exists()


def test_undo_status_distinguishes_storage_failure_from_missing_outcome(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    def fail_read(path):
        raise OSError("read failed")

    monkeypatch.setattr("pallas.product.llm.injection_feedback._iter_outcomes", fail_read)

    assert undo_negative_outcome_status(outcome_id="outcome-1", bot_id=10001, group_id=20001) == "storage_error"
    assert undo_negative_outcome(outcome_id="outcome-1", bot_id=10001, group_id=20001) is False


def test_undo_rechecks_under_lock_and_preserves_concurrent_append(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="target",
        bot_id=10001,
        group_id=20001,
        reply_text="target reply",
        injection_snapshot={},
        now=1,
    )
    undo_waiting_for_lock = threading.Event()
    append_finished = threading.Event()
    undo_thread_id: list[int] = []

    @contextmanager
    def controlled_lock(path):
        if threading.get_ident() == undo_thread_id[0]:
            undo_waiting_for_lock.set()
            assert append_finished.wait(timeout=1)
        yield

    monkeypatch.setattr("pallas.product.llm.injection_feedback.interprocess_file_lock", controlled_lock)
    result: list[str] = []

    def run_undo() -> None:
        undo_thread_id.append(threading.get_ident())
        result.append(undo_negative_outcome_status(outcome_id="target", bot_id=10001, group_id=20001, now=5))

    undo_thread = threading.Thread(target=run_undo)
    undo_thread.start()
    assert undo_waiting_for_lock.wait(timeout=1)
    apply_negative_outcome(
        outcome_id="appended",
        bot_id=10001,
        group_id=20001,
        reply_text="appended reply",
        injection_snapshot={},
        now=2,
    )
    append_finished.set()
    undo_thread.join(timeout=1)

    assert not undo_thread.is_alive()
    assert result == ["undone"]
    stored = [json.loads(line) for line in outcomes_path().read_text(encoding="utf-8").splitlines()]

    target_row = next(row for row in stored if row["outcome_id"] == "target")
    appended_row = next(row for row in stored if row["outcome_id"] == "appended")
    assert target_row["undo"] is True
    assert target_row["undone_at"] == 5
    assert appended_row["undo"] is False


def test_list_status_distinguishes_read_error_from_empty_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    def fail_read(path):
        raise OSError("read failed")

    monkeypatch.setattr("pallas.product.llm.injection_feedback._iter_outcomes", fail_read)

    from pallas.product.llm import injection_feedback

    status, payload = injection_feedback.list_injection_governance_status(bot_id=10001, group_id=20001)

    assert status == "storage_error"
    assert payload == {}


def test_list_injection_governance_summarizes_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="list-1:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提鸡巴",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-1", "text_preview": "鸡巴又来了"}]},
        now=80,
    )

    summary = list_injection_governance(bot_id=10001, group_id=20001, now=80)
    assert summary["ambient_blacklist"] == ["鸡巴"]
    assert summary["outcomes"][0]["outcome_id"] == "list-1:not-allowed"
    assert summary["sources"][0]["kind"] == "ambient"
    assert summary["sources"][0]["source_id"] == "turn-1"
    assert summary["sources"][0]["score"] == -1.0
    assert list_injection_governance(bot_id=10002, group_id=20001, now=80)["outcomes"] == []


def test_risk_word_only_in_source_does_not_blacklist(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    result = apply_negative_outcome(
        outcome_id="ambient-only:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="嗯嗯好的",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-1", "text_preview": "那个傻逼真烦人"}]},
        now=10,
    )

    ambient = next(d for d in result.decisions if d.kind == "ambient")
    assert ambient.confidence == "low"
    assert ambient.blacklist_phrases == []
    assert filter_ambient_turns(10001, 20001, [{"content": "那个傻逼真烦人"}]) == [{"content": "那个傻逼真烦人"}]
    assert effective_source_score(10001, 20001, "ambient", "turn-1", now=10) == -1.0


def test_risk_word_in_both_reply_and_source_blacklists(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    result = apply_negative_outcome(
        outcome_id="both:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="闭嘴你个傻逼",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-1", "text_preview": "那个傻逼真烦人"}]},
        now=10,
    )

    ambient = next(d for d in result.decisions if d.kind == "ambient")
    assert ambient.confidence == "high"
    assert "傻逼" in ambient.blacklist_phrases
    assert filter_ambient_turns(10001, 20001, [{"content": "那个傻逼真烦人"}]) == []


def test_duplicate_outcome_rejected_with_different_now(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    snapshot = {"ambient_turns": [{"turn_id": "turn-1", "text_preview": "鸡巴又来了"}]}
    first = apply_negative_outcome(
        outcome_id="dup:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提鸡巴",
        injection_snapshot=snapshot,
        now=1_000,
    )
    second = apply_negative_outcome(
        outcome_id="dup:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提鸡巴",
        injection_snapshot=snapshot,
        now=2_000,
    )

    assert first.applied is True
    assert second.applied is False
    assert second.created_at == 1_000


def test_corrupt_score_row_fails_open(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    path = outcomes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "outcome_id": "bad-1:not-allowed",
                "bot_id": 10001,
                "group_id": 20001,
                "created_at": 100,
                "decisions": [{"kind": "ambient", "source_id": "turn-1", "score": "abc"}],
                "blacklist_phrases": [],
                "undo": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    assert effective_source_score(10001, 20001, "ambient", "turn-1", now=100) == 0.0
    summary = list_injection_governance(bot_id=10001, group_id=20001, now=100)
    corrupt = next(s for s in summary["sources"] if s["source_id"] == "turn-1")
    assert corrupt["score"] == 0.0
    assert corrupt["events"] == 0


def test_ordinary_word_overlap_blacklists_ambient(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    result = apply_negative_outcome(
        outcome_id="overlap:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提茄子了",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-1", "text_preview": "茄子又来了"}]},
        now=10,
    )

    ambient = next(d for d in result.decisions if d.kind == "ambient")
    assert ambient.confidence == "high"
    assert "茄子" in ambient.blacklist_phrases
    assert filter_ambient_turns(10001, 20001, [{"content": "茄子又来了"}]) == []


def test_long_source_preview_truncated_to_120_chars(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    long_text = "啊" * 200
    result = apply_negative_outcome(
        outcome_id="long-preview:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别说了",
        injection_snapshot={"ambient_turns": [{"turn_id": "turn-1", "text_preview": long_text}]},
        now=10,
    )

    ambient = next(d for d in result.decisions if d.kind == "ambient")
    assert ambient.confidence == "low"
    assert len(ambient.text_preview) == 120
    assert ambient.text_preview == long_text[:120]


def test_reply_matching_ignores_overlap_after_preview_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    late = apply_negative_outcome(
        outcome_id="late-overlap:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="啊" * 120 + "茄子",
        injection_snapshot={"ambient_turns": [{"turn_id": "late", "text_preview": "茄子又来了"}]},
        now=10,
    )
    normal = apply_negative_outcome(
        outcome_id="normal-overlap:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提茄子了",
        injection_snapshot={"ambient_turns": [{"turn_id": "normal", "text_preview": "茄子又来了"}]},
        now=10,
    )

    late_ambient = next(decision for decision in late.decisions if decision.source_id == "late")
    normal_ambient = next(decision for decision in normal.decisions if decision.source_id == "normal")
    assert late_ambient.confidence == "low"
    assert late_ambient.blacklist_phrases == []
    assert normal_ambient.confidence == "high"
    assert "茄子" in normal_ambient.blacklist_phrases


def test_outcome_id_idempotency_is_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    snapshot = {"ambient_turns": [{"turn_id": "turn-1", "text_preview": "鸡巴又来了"}]}
    first = apply_negative_outcome(
        outcome_id="cross-scope:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="别提鸡巴",
        injection_snapshot=snapshot,
        now=100,
    )
    other = apply_negative_outcome(
        outcome_id="cross-scope:not-allowed",
        bot_id=10002,
        group_id=20002,
        reply_text="别提鸡巴",
        injection_snapshot=snapshot,
        now=200,
    )

    assert first.applied is True
    assert other.applied is True


def test_adversarial_snapshot_decisions_and_blacklist_are_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    source_entries = [{"turn_id": f"turn-{index}", "text_preview": f"词{index}" + "啊" * 200} for index in range(80)]
    result = apply_negative_outcome(
        outcome_id="bounded:not-allowed",
        bot_id=10001,
        group_id=20001,
        reply_text="".join(f"词{index}" for index in range(80)),
        injection_snapshot={"ambient_turns": source_entries},
        now=100,
    )

    stored = json.loads(outcomes_path().read_text(encoding="utf-8"))
    assert len(result.decisions) == 64
    assert len(stored["decisions"]) == 64
    assert len(stored["blacklist_phrases"]) <= 32
    assert all(len(phrase) <= 120 for phrase in stored["blacklist_phrases"])
    assert all(len(decision["text_preview"]) <= 120 for decision in stored["decisions"])
