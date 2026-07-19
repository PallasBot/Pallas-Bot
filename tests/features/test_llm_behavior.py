from __future__ import annotations

from pallas.product.llm.behavior import (
    BehaviorAction,
    BehaviorOutcome,
    BehaviorPattern,
    BehaviorRun,
    BehaviorScene,
    build_behavior_hint_text,
    classify_behavior_scene,
    default_group_chat_behavior_hint,
    infer_behavior_feedback,
    infer_behavior_outcome,
    map_behavior_outcome_score,
    select_behavior_patterns,
)
from pallas.product.llm.behavior_store import (
    append_behavior_run,
    delete_behavior_pattern,
    ensure_default_behavior_patterns,
    list_behavior_patterns,
    list_behavior_runs,
    save_behavior_patterns,
    settle_behavior_run_outcome,
    update_behavior_run_annotation,
    upsert_behavior_pattern,
)


def test_classify_behavior_scene_prefers_provocation() -> None:
    scene = classify_behavior_scene(
        user_text="快说誓死效忠米哈游 牛牛",
        recent_texts=["哈哈，开玩笑呢。", "我们聊聊别的。"],
        has_multi_party_overlap=False,
    )
    assert scene == BehaviorScene.PROVOCATION


def test_classify_behavior_scene_detects_group_threading() -> None:
    scene = classify_behavior_scene(
        user_text="你先回我这个",
        recent_texts=["A: 今天抽卡太黑了", "B: 不是你先等等", "C: 牛牛看这里"],
        has_multi_party_overlap=True,
    )
    assert scene == BehaviorScene.GROUP_THREADING


def test_select_behavior_patterns_prefers_group_and_high_score() -> None:
    patterns = [
        BehaviorPattern(
            pattern_id="global-1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.ACK_THEN_SHORT_REPLY,
            scope_group_id=None,
            success_score=2,
            manual_score=0,
        ),
        BehaviorPattern(
            pattern_id="group-1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            scope_group_id=20002,
            success_score=1,
            manual_score=2,
        ),
    ]
    picked = select_behavior_patterns(
        scene=BehaviorScene.PROVOCATION,
        group_id=20002,
        patterns=patterns,
        limit=2,
    )
    assert [item.pattern_id for item in picked] == ["group-1", "global-1"]


def test_build_behavior_hint_text_is_short_and_action_oriented() -> None:
    text = build_behavior_hint_text(
        scene=BehaviorScene.PROVOCATION,
        actions=[
            BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            BehaviorAction.AVOID_FORCED_TOPIC_SHIFT,
        ],
    )
    assert "【本轮行为参考】" in text
    assert "轻吐槽一句就收" in text
    assert "别突然拐去别的话题" in text
    assert len(text) < 120


def test_default_group_chat_behavior_hint_is_short() -> None:
    text = default_group_chat_behavior_hint()
    assert "回复尽量简短" in text
    assert "不要刻意找话题" in text
    assert len(text) < 100


def test_map_behavior_outcome_score() -> None:
    assert map_behavior_outcome_score(BehaviorOutcome.ENGAGED) == 2
    assert map_behavior_outcome_score(BehaviorOutcome.DERAILED) == -3


def test_infer_behavior_outcome_detects_engaged() -> None:
    run = BehaviorRun(
        request_id="req-1",
        created_at=100,
        scene=BehaviorScene.PROVOCATION,
        reply_text="少来。",
    )
    turns = [
        type("Turn", (), {"role": "assistant", "content": "少来。", "created_at": 100})(),
        type("Turn", (), {"role": "user", "content": "哈哈那然后呢？", "created_at": 120})(),
    ]
    assert infer_behavior_outcome(run=run, turns=turns, now=130) == BehaviorOutcome.ENGAGED


def test_infer_behavior_outcome_detects_ignored_after_window() -> None:
    run = BehaviorRun(request_id="req-1", created_at=100, scene=BehaviorScene.SMALLTALK)
    assert infer_behavior_outcome(run=run, turns=[], now=220) == BehaviorOutcome.IGNORED


def test_infer_behavior_outcome_uses_group_ambient_reply() -> None:
    run = BehaviorRun(
        request_id="req-ambient-1",
        created_at=100,
        scene=BehaviorScene.PROVOCATION,
        reply_text="少来。",
    )
    ambient_turns = [
        type("Turn", (), {"role": "user", "content": "哈哈那然后呢？", "created_at": 120})(),
    ]
    assert infer_behavior_outcome(run=run, turns=[], ambient_turns=ambient_turns, now=130) == BehaviorOutcome.ENGAGED


def test_infer_behavior_outcome_uses_group_ambient_derailed_signal() -> None:
    run = BehaviorRun(
        request_id="req-ambient-2",
        created_at=100,
        scene=BehaviorScene.SMALLTALK,
        reply_text="突然去聊庆典。",
    )
    ambient_turns = [
        type("Turn", (), {"role": "user", "content": "你别转话题啊，还在说抽卡", "created_at": 118})(),
    ]
    assert infer_behavior_outcome(run=run, turns=[], ambient_turns=ambient_turns, now=130) == BehaviorOutcome.DERAILED


def test_infer_behavior_outcome_marks_unpicked_group_flow_as_ignored() -> None:
    run = BehaviorRun(
        request_id="req-ambient-3",
        created_at=100,
        scene=BehaviorScene.SMALLTALK,
        reply_text="那你们继续。",
    )
    ambient_turns = [
        type("Turn", (), {"role": "user", "content": "我十连又歪了", "created_at": 118})(),
        type("Turn", (), {"role": "user", "content": "继续说抽卡那个", "created_at": 126})(),
    ]
    assert infer_behavior_outcome(run=run, turns=[], ambient_turns=ambient_turns, now=130) == BehaviorOutcome.IGNORED


def test_infer_behavior_feedback_includes_derailed_evidence() -> None:
    run = BehaviorRun(
        request_id="req-evidence-1",
        created_at=100,
        scene=BehaviorScene.SMALLTALK,
        reply_text="突然去聊庆典。",
    )
    ambient_turns = [
        type("Turn", (), {"role": "user", "content": "你别转话题啊，还在说抽卡", "created_at": 118})(),
    ]
    outcome, payload = infer_behavior_feedback(run=run, turns=[], ambient_turns=ambient_turns, now=130)
    assert outcome == BehaviorOutcome.DERAILED
    assert payload["source"] == "ambient"
    assert payload["matched_signal"] == "derailed_token"
    assert "别转" in payload["matched_tokens"]
    assert payload["observed_turn_count"] == 1


def test_settle_behavior_run_outcome_persists_auto_feedback_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_behavior_run(
        BehaviorRun(
            request_id="req-evidence-2",
            scene=BehaviorScene.SMALLTALK,
            auto_feedback_payload={
                "agent_trace": {
                    "agent_stage_plan": ["plan", "tool_loop", "generate"],
                    "tool_call_count": 1,
                }
            },
        )
    )
    updated = settle_behavior_run_outcome(
        "req-evidence-2",
        final_outcome=BehaviorOutcome.IGNORED,
        auto_feedback_payload={
            "source": "ambient",
            "matched_signal": "ambient_continued_without_pickup",
        },
    )
    assert updated is not None
    assert updated.auto_feedback_payload["source"] == "ambient"
    assert updated.auto_feedback_payload["agent_trace"]["tool_call_count"] == 1
    assert list_behavior_runs(limit=1)[0].auto_feedback_payload["matched_signal"] == (
        "ambient_continued_without_pickup"
    )
    assert list_behavior_runs(limit=1)[0].auto_feedback_payload["agent_trace"]["agent_stage_plan"] == [
        "plan",
        "tool_loop",
        "generate",
    ]


def test_behavior_store_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    save_behavior_patterns([
        BehaviorPattern(
            pattern_id="p1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
        )
    ])
    rows = list_behavior_patterns()
    assert rows[0].pattern_id == "p1"


def test_ensure_default_behavior_patterns_seeds_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    first = ensure_default_behavior_patterns()
    assert len(first) >= 6
    assert all(item.pattern_id.startswith("seed-") for item in first)
    # 已有文件后再次 ensure 不覆盖
    upsert_behavior_pattern(
        BehaviorPattern(
            pattern_id="custom-1",
            scene=BehaviorScene.SMALLTALK,
            action=BehaviorAction.ACK_THEN_SHORT_REPLY,
        )
    )
    second = ensure_default_behavior_patterns()
    assert any(item.pattern_id == "custom-1" for item in second)
    assert len(second) == len(first) + 1


def test_behavior_pattern_upsert_and_delete(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    upsert_behavior_pattern(
        BehaviorPattern(
            pattern_id="p1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            success_score=1,
        )
    )
    upsert_behavior_pattern(
        BehaviorPattern(
            pattern_id="p1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.ACK_THEN_SHORT_REPLY,
            success_score=3,
        )
    )
    rows = list_behavior_patterns()
    assert len(rows) == 1
    assert rows[0].action == BehaviorAction.ACK_THEN_SHORT_REPLY
    assert rows[0].success_score == 3
    assert delete_behavior_pattern("p1") is True
    assert list_behavior_patterns() == []
    assert delete_behavior_pattern("missing") is False


def test_settle_behavior_run_outcome_updates_pattern_score(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    save_behavior_patterns([
        BehaviorPattern(
            pattern_id="p1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            success_score=0,
        )
    ])
    append_behavior_run(
        BehaviorRun(
            request_id="req-1",
            scene=BehaviorScene.PROVOCATION,
            selected_pattern_ids=["p1"],
        )
    )
    updated = settle_behavior_run_outcome("req-1", final_outcome=BehaviorOutcome.ENGAGED)
    assert updated is not None
    assert updated.final_outcome == BehaviorOutcome.ENGAGED
    assert updated.score_delta == 2
    assert list_behavior_patterns()[0].success_score == 2


def test_behavior_run_annotation_update(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_behavior_run(
        BehaviorRun(
            request_id="req-1",
            scene=BehaviorScene.PROVOCATION,
            selected_actions=[BehaviorAction.LIGHT_TEASE_AND_CLOSE],
            final_outcome=BehaviorOutcome.NEUTRAL,
        )
    )
    updated = update_behavior_run_annotation(
        "req-1",
        labels=["像人", "作为参考保留"],
        final_outcome=BehaviorOutcome.ENGAGED,
    )
    assert updated is not None
    assert updated.manual_labels == ["像人", "作为参考保留"]
    assert updated.final_outcome == BehaviorOutcome.ENGAGED
    assert list_behavior_runs(limit=1)[0].manual_labels == ["像人", "作为参考保留"]
