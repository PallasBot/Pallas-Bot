from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pallas.product.llm.repeater_semantic_style import (
    SEMANTIC_STYLE_LABEL_VERSION,
    SemanticStyleExample,
    append_cached_semantic_style_block,
    build_cached_semantic_style_block,
    clear_semantic_style_cache_for_tests,
    is_positive_bot_style_outcome,
    parse_semantic_style_label,
    persist_semantic_style_example,
    prune_semantic_style_examples,
    record_bot_style_outcome,
)


def test_backfill_batch_bounds_history_window_and_advances_cursor() -> None:
    from pallas.product.llm.repeater_semantic_style import (
        SemanticStyleBackfillCursor,
        build_semantic_style_backfill_batch,
    )

    batch = build_semantic_style_backfill_batch(
        [
            {
                "message_id": 3,
                "created_at": 10_000,
                "bot_id": 100,
                "group_id": 42,
                "trigger_text": "前句",
                "reply_text": "接话",
            },
            {
                "message_id": 2,
                "created_at": 10_000 - 31 * 24 * 60 * 60,
                "bot_id": 100,
                "group_id": 42,
                "trigger_text": "过期历史",
                "reply_text": "不应入队",
            },
            {
                "message_id": 1,
                "created_at": 9_000,
                "bot_id": 100,
                "group_id": 42,
                "trigger_text": "更早前句",
                "reply_text": "更早接话",
            },
        ],
        cursor=SemanticStyleBackfillCursor(),
        now=10_000,
        remaining_today=1,
    )

    assert [job.payload["message_id"] for job in batch.jobs] == [3]
    assert batch.cursor.before_message_id == 3
    assert batch.cursor.before_created_at == 10_000
    assert batch.jobs[0].payload["expires_at"] == 10_000 + 7 * 24 * 60 * 60
    assert batch.deferred is True


def test_backfill_batch_defers_to_new_semantic_jobs() -> None:
    from pallas.product.llm.repeater_semantic_style import build_semantic_style_backfill_batch

    batch = build_semantic_style_backfill_batch(
        [
            {
                "message_id": 3,
                "created_at": 10_000,
                "bot_id": 100,
                "group_id": 42,
                "trigger_text": "前句",
                "reply_text": "接话",
            }
        ],
        now=10_000,
        remaining_today=10,
        has_pending_new_jobs=True,
    )

    assert batch.jobs == []
    assert batch.deferred is True


def test_backfill_batch_advances_past_candidates_outside_the_history_window() -> None:
    from pallas.product.llm.repeater_semantic_style import build_semantic_style_backfill_batch

    batch = build_semantic_style_backfill_batch(
        [
            {
                "message_id": 2,
                "created_at": 10_000 - 31 * 24 * 60 * 60,
                "bot_id": 100,
                "group_id": 42,
                "trigger_text": "过期历史",
                "reply_text": "不应入队",
            },
            {
                "message_id": 1,
                "created_at": 10_000 - 32 * 24 * 60 * 60,
                "bot_id": 100,
                "group_id": 42,
                "trigger_text": "更旧历史",
                "reply_text": "不应入队",
            },
        ],
        now=10_000,
    )

    assert batch.jobs == []
    assert batch.cursor.before_message_id == 1


@pytest.mark.asyncio
async def test_semantic_style_backfill_handler_skips_expired_and_retries_label_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    label = parse_semantic_style_label({"reuse": "rewrite"})
    worker = AsyncMock(side_effect=[RuntimeError("temporary"), RuntimeError("temporary"), label])
    persist = Mock()
    monkeypatch.setattr(mod, "label_semantic_style_with_llm", worker)
    monkeypatch.setattr(mod, "persist_semantic_style_example", persist)

    payload = {
        "example_id": "42:99:100",
        "message_id": 99,
        "created_at": 10_000,
        "expires_at": 10_001,
        "bot_id": 100,
        "group_id": 42,
        "scene": "group_chat",
        "trigger_text": "前句",
        "reply_text": "接话",
    }
    await mod.handle_repeater_semantic_style_backfill(payload, now=10_000)

    assert worker.await_count == 3
    assert persist.called

    await mod.handle_repeater_semantic_style_backfill(payload, now=10_001)
    assert worker.await_count == 3


@pytest.mark.asyncio
async def test_semantic_style_handlers_skip_disabled_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    worker = AsyncMock()
    monkeypatch.setattr(mod, "label_semantic_style_with_llm", worker)
    monkeypatch.setattr(mod, "semantic_style_collection_enabled", lambda *, bot_id, group_id: False)
    payload = {
        "example_id": "42:99:100",
        "message_id": 99,
        "created_at": 10_000,
        "expires_at": 10_001,
        "bot_id": 100,
        "group_id": 42,
        "scene": "group_chat",
        "trigger_text": "前句",
        "reply_text": "接话",
    }

    await mod.handle_repeater_semantic_style(payload)
    await mod.handle_repeater_semantic_style_backfill(payload, now=10_000)

    worker.assert_not_awaited()


def test_realtime_admission_respects_persistent_global_and_scope_budgets(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(mod, "SEMANTIC_STYLE_REALTIME_SAMPLE_DIVISOR", 1)
    monkeypatch.setattr(mod, "SEMANTIC_STYLE_REALTIME_MAX_PER_DAY", 2)
    monkeypatch.setattr(mod, "SEMANTIC_STYLE_REALTIME_MAX_PER_SCOPE_PER_DAY", 1)

    assert mod.claim_semantic_style_realtime_admission(bot_id=100, group_id=42, example_id="a", now=10_000)
    assert not mod.claim_semantic_style_realtime_admission(bot_id=100, group_id=42, example_id="b", now=10_000)
    assert mod.claim_semantic_style_realtime_admission(bot_id=100, group_id=43, example_id="c", now=10_000)
    assert not mod.claim_semantic_style_realtime_admission(bot_id=100, group_id=44, example_id="d", now=10_000)


@pytest.mark.asyncio
async def test_realtime_handler_drops_legacy_job_when_budget_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    worker = AsyncMock()
    monkeypatch.setattr(mod, "label_semantic_style_with_llm", worker)
    monkeypatch.setattr(mod, "semantic_style_collection_enabled", lambda **_kwargs: True)
    monkeypatch.setattr(mod, "claim_semantic_style_realtime_admission", lambda **_kwargs: False)

    await mod.handle_repeater_semantic_style({
        "example_id": "42:99:100",
        "bot_id": 100,
        "group_id": 42,
        "trigger_text": "前句",
        "reply_text": "接话",
    })

    worker.assert_not_awaited()


@pytest.mark.asyncio
async def test_semantic_style_label_uses_deterministic_short_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    complete = AsyncMock(return_value={"content": "{}"})
    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", complete)
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: SimpleNamespace(llm_model="test-model"),
    )

    await mod.label_semantic_style_with_llm(trigger_text="前句", reply_text="接话")

    assert complete.await_args.kwargs["options"] == {"temperature": 0, "max_tokens": 96}


@pytest.mark.asyncio
async def test_collect_backfill_candidates_uses_online_bot_groups_and_verified_reply_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm.repeater_semantic_style import collect_semantic_style_backfill_candidates

    now = 2_000_000_000

    class DummyMessageRepo:
        async def list_recent_group_ids_for_bot(self, bot_id: int, *, since_time: int, limit: int):
            assert bot_id == 100
            assert since_time == now - 30 * 24 * 60 * 60
            assert limit == 128
            return [42]

        async def find_recent_in_group(self, group_id: int, *, before_time: int, limit: int):
            assert group_id == 42
            assert limit == 32
            if before_time == now + 1:
                return [
                    SimpleNamespace(
                        group_id=42,
                        user_id=11,
                        bot_id=100,
                        plain_text="又炸了",
                        raw_message="又炸了",
                        time=now - 20,
                    ),
                    SimpleNamespace(
                        group_id=42,
                        user_id=100,
                        bot_id=100,
                        plain_text="没救了",
                        raw_message="没救了",
                        time=now - 10,
                    ),
                    SimpleNamespace(
                        group_id=42,
                        user_id=100,
                        bot_id=100,
                        plain_text="未学习回复",
                        raw_message="未学习回复",
                        time=now - 5,
                    ),
                ]
            return []

    class DummyContextRepo:
        async def list_answers_for_group_since(self, group_id: int, cutoff_time: int):
            assert (group_id, cutoff_time) == (42, now - 30 * 24 * 60 * 60)
            return [SimpleNamespace(time=now - 10, messages=["没救了"])]

    monkeypatch.setattr(
        "pallas.product.llm.repeater_semantic_style.make_message_repository",
        lambda: DummyMessageRepo(),
    )
    monkeypatch.setattr(
        "pallas.product.llm.repeater_semantic_style.make_local_context_repository",
        lambda: DummyContextRepo(),
    )

    candidates = await collect_semantic_style_backfill_candidates(now=now, bot_ids=[100])

    assert len(candidates) == 1
    assert candidates[0]["bot_id"] == 100
    assert candidates[0]["group_id"] == 42
    assert candidates[0]["trigger_text"] == "又炸了"
    assert candidates[0]["reply_text"] == "没救了"


@pytest.mark.asyncio
async def test_backfill_round_enqueues_scan_without_scanning_in_unified_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    collect = AsyncMock()
    store = SimpleNamespace(enqueue=AsyncMock())
    monkeypatch.setattr(mod, "collect_semantic_style_backfill_candidates", collect)
    monkeypatch.setattr(mod, "build_work_job_store", lambda: store)
    monkeypatch.setattr(mod, "get_bots", lambda: {"100": SimpleNamespace(self_id="100")})

    assert await mod.run_semantic_style_backfill_round(now=2_000_000_000) == 1
    collect.assert_not_awaited()
    job = store.enqueue.await_args.args[0]
    assert job.kind == "repeater.semantic_style.backfill.scan"
    assert job.payload == {"bot_ids": [100], "now": 2_000_000_000}
    assert job.idempotency_key == "repeater.semantic_style.backfill.scan:23148"


@pytest.mark.asyncio
async def test_backfill_scan_handler_persists_jobs_before_advancing_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    now = 2_000_000_000
    cursor = mod.SemanticStyleBackfillCursor()
    next_cursor = mod.SemanticStyleBackfillCursor(before_created_at=now - 10, before_message_id=99)
    collected = [
        {
            "message_id": 99,
            "created_at": now - 10,
            "bot_id": 100,
            "group_id": 42,
            "trigger_text": "前句",
            "reply_text": "接话",
        }
    ]
    store = SimpleNamespace(enqueue_many=AsyncMock())
    saved = Mock()
    monkeypatch.setattr(mod, "load_semantic_style_backfill_cursor", lambda: cursor)
    monkeypatch.setattr(mod, "collect_semantic_style_backfill_candidates", AsyncMock(return_value=collected))
    monkeypatch.setattr(
        mod,
        "build_semantic_style_backfill_batch",
        lambda *args, **kwargs: mod.SemanticStyleBackfillBatch(
            jobs=[
                mod.WorkJob.create(
                    kind="repeater.semantic_style.backfill",
                    payload={"message_id": 99},
                    idempotency_key="repeater.semantic_style.backfill:42:99:100",
                )
            ],
            cursor=next_cursor,
        ),
    )
    monkeypatch.setattr(mod, "build_work_job_store", lambda: store)
    monkeypatch.setattr(mod, "save_semantic_style_backfill_cursor", saved)

    assert await mod.handle_repeater_semantic_style_backfill_scan({"bot_ids": [100], "now": now}) == 1

    mod.collect_semantic_style_backfill_candidates.assert_awaited_once_with(now=now, bot_ids=[100], cursor=cursor)
    store.enqueue_many.assert_awaited_once()
    saved.assert_called_once_with(next_cursor)


@pytest.mark.asyncio
async def test_backfill_scan_handler_keeps_cursor_when_enqueue_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    cursor = mod.SemanticStyleBackfillCursor()
    store = SimpleNamespace(enqueue_many=AsyncMock(side_effect=RuntimeError("database unavailable")))
    saved = Mock()
    monkeypatch.setattr(mod, "load_semantic_style_backfill_cursor", lambda: cursor)
    monkeypatch.setattr(mod, "collect_semantic_style_backfill_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        mod,
        "build_semantic_style_backfill_batch",
        lambda *args, **kwargs: mod.SemanticStyleBackfillBatch(
            jobs=[
                mod.WorkJob.create(
                    kind="repeater.semantic_style.backfill",
                    payload={"message_id": 99},
                    idempotency_key="repeater.semantic_style.backfill:42:99:100",
                )
            ],
            cursor=cursor,
        ),
    )
    monkeypatch.setattr(mod, "build_work_job_store", lambda: store)
    monkeypatch.setattr(mod, "save_semantic_style_backfill_cursor", saved)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await mod.handle_repeater_semantic_style_backfill_scan({"bot_ids": [100], "now": 2_000_000_000})
    saved.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_scan_handler_ignores_invalid_bot_ids() -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    assert await mod.handle_repeater_semantic_style_backfill_scan({"bot_ids": ["invalid", 0, -1]}) == 0


def test_parse_label_accepts_multi_axis_direct_example() -> None:
    label = parse_semantic_style_label({
        "interaction_actions": ["tease", "tease"],
        "semantic_relations": ["disagree", "joke"],
        "intensity": "sharp",
        "forms": ["short"],
        "outcome": "engaged",
        "reuse": "direct",
        "persona_affinities": ["mouthy"],
        "style_anchor": "短句轻怼，不解释。",
    })

    assert label.interaction_actions == ["tease"]
    assert label.reuse == "direct"
    assert label.style_anchor == "短句轻怼，不解释。"


def test_semantic_style_management_persists_controls_and_rebuilds_data(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    mod.clear_semantic_style_cache_for_tests()
    mod.persist_semantic_style_example(
        mod.SemanticStyleExample(
            example_id="42:1:100",
            created_at=100,
            bot_id=100,
            group_id=42,
            scene="group_chat",
            trigger_text="前句",
            reply_text="接话",
            label=mod.parse_semantic_style_label({"reuse": "direct"}),
        )
    )

    assert mod.semantic_style_status()["enabled"] is True
    assert mod.update_semantic_style_overrides({"direct": False})["overrides"]["direct"] is False
    assert mod.update_semantic_style_overrides({"image": False})["overrides"] == {
        "aggressive": True,
        "nonsense": True,
        "direct": False,
        "image": False,
    }
    assert mod.set_semantic_style_enabled(False)["enabled"] is False
    assert mod.rebuild_semantic_style_profiles()["profile_count"] == 1
    assert mod.semantic_style_quality()["example_count"] == 1
    assert mod.clear_semantic_style_data()["example_count"] == 0
    assert mod.recover_semantic_style_data()["profile_count"] == 0


def test_semantic_style_management_isolated_by_bot_and_group_with_global_fallback(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    mod.clear_semantic_style_cache_for_tests()
    for bot_id, group_id in ((100, 42), (101, 43)):
        mod.persist_semantic_style_example(
            mod.SemanticStyleExample(
                example_id=f"{group_id}:1:{bot_id}",
                created_at=100,
                bot_id=bot_id,
                group_id=group_id,
                scene="group_chat",
                trigger_text="前句",
                reply_text="接话",
                label=mod.parse_semantic_style_label({"reuse": "direct"}),
            )
        )

    assert (
        mod.update_semantic_style_overrides({"direct": False}, bot_id=100, group_id=42)["overrides"]["direct"] is False
    )
    assert mod.semantic_style_status(bot_id=101, group_id=43)["overrides"]["direct"] is True
    assert mod.set_semantic_style_enabled(False, bot_id=100, group_id=42)["enabled"] is False
    assert mod.semantic_style_injection_enabled("scope-disabled", bot_id=100, group_id=42) is False
    assert mod.semantic_style_status()["enabled"] is True
    assert mod.semantic_style_status(bot_id=100, group_id=42)["example_count"] == 1
    assert mod.rebuild_semantic_style_profiles(bot_id=100, group_id=42)["profile_count"] == 1
    assert mod.clear_semantic_style_data(bot_id=100, group_id=42)["example_count"] == 0
    assert mod.semantic_style_status(bot_id=101, group_id=43)["example_count"] == 1
    assert mod.semantic_style_status()["example_count"] == 1


def test_parse_label_falls_back_to_safe_defaults_for_invalid_values() -> None:
    label = parse_semantic_style_label({"reuse": "unknown", "intensity": "loud", "outcome": "bad"})

    assert label.reuse == "style"
    assert label.intensity == "neutral"
    assert label.outcome == "unknown"


def test_parse_label_rejects_values_outside_controlled_vocabularies() -> None:
    label = parse_semantic_style_label({
        "interaction_actions": ["tease", "new_provider_category"],
        "semantic_relations": ["echo", "invented_relation"],
        "forms": ["short", "wall_of_text"],
        "persona_affinities": ["mouthy", "unbounded_persona"],
    })

    assert label.interaction_actions == ["tease"]
    assert label.semantic_relations == ["echo"]
    assert label.forms == ["short"]
    assert label.persona_affinities == ["mouthy"]
    assert SEMANTIC_STYLE_LABEL_VERSION >= 1


def test_cached_style_block_is_scoped_to_bot_group_and_scene(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_semantic_style_cache_for_tests()
    profile = persist_semantic_style_example(
        SemanticStyleExample(
            example_id="42:99:100",
            created_at=20,
            bot_id=100,
            group_id=42,
            scene="group_chat",
            trigger_text="又炸了",
            reply_text="没救了",
            label=parse_semantic_style_label({"reuse": "direct", "style_anchor": "短句轻怼，不解释。"}),
        )
    )

    block = build_cached_semantic_style_block(100, 42, "group_chat")

    assert "短句轻怼，不解释。" in block
    assert "没救了" in block
    assert profile.direct_examples == ["没救了"]
    assert profile.rewrite_seeds == []
    assert build_cached_semantic_style_block(101, 42, "group_chat") == ""
    assert build_cached_semantic_style_block(100, 42, "other") == ""


def test_append_cached_style_block_preserves_base_prompt() -> None:
    assert append_cached_semantic_style_block("原始人设", "短句轻怼", "没救了") == (
        "原始人设\n\n【本群表达校准】\n保持：短句轻怼\n可借鉴句式：没救了"
    )


def test_semantic_style_injection_cohort_is_stable_and_keeps_ten_percent_out() -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    request_ids = [f"semantic-style-cohort-{index}" for index in range(10_000)]
    first = [mod.semantic_style_injection_enabled(request_id) for request_id in request_ids]

    assert first == [mod.semantic_style_injection_enabled(request_id) for request_id in request_ids]
    assert 900 <= sum(not enabled for enabled in first) <= 1_100


def test_cached_semantic_style_resolution_reads_prompt_block_and_direct_candidate_from_cache(
    tmp_path, monkeypatch
) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_semantic_style_cache_for_tests()
    persist_semantic_style_example(
        SemanticStyleExample(
            example_id="42:100:99",
            created_at=100,
            bot_id=99,
            group_id=42,
            scene="group_chat",
            trigger_text="又炸了",
            reply_text="没救了",
            label=parse_semantic_style_label({"reuse": "direct", "style_anchor": "短句轻怼。"}),
        )
    )

    request_id = next(
        item for item in (f"request-{index}" for index in range(100)) if mod.semantic_style_injection_enabled(item)
    )
    resolution = mod.resolve_cached_semantic_style(99, 42, "group_chat", request_id=request_id)

    assert resolution.style_anchor == "短句轻怼。"
    assert resolution.direct_candidate == "没救了"
    assert "本群表达校准" in resolution.prompt_block


def test_semantic_style_direct_quota_allows_only_one_before_twenty_then_fifteen_per_hundred() -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    mod.clear_semantic_style_direct_quota_for_tests()

    decisions = [
        mod.should_deliver_semantic_style_direct_candidate(bot_id=99, group_id=42, candidate="没救了")
        for _ in range(20)
    ]
    assert sum(decisions) == 1

    for _ in range(80):
        mod.should_deliver_semantic_style_direct_candidate(bot_id=99, group_id=42, candidate=None)
    assert (
        sum(
            mod.should_deliver_semantic_style_direct_candidate(bot_id=99, group_id=42, candidate="没救了")
            for _ in range(100)
        )
        == 15
    )


def test_profile_caps_direct_and_rewrite_examples(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_semantic_style_cache_for_tests()
    for index in range(4):
        persist_semantic_style_example(
            SemanticStyleExample(
                example_id=f"direct:{index}",
                created_at=index + 1,
                bot_id=100,
                group_id=42,
                scene="group_chat",
                trigger_text="前句",
                reply_text=f"直出 {index}",
                label=parse_semantic_style_label({"reuse": "direct"}),
            )
        )
        persist_semantic_style_example(
            SemanticStyleExample(
                example_id=f"rewrite:{index}",
                created_at=index + 10,
                bot_id=100,
                group_id=42,
                scene="group_chat",
                trigger_text="前句",
                reply_text=f"改写 {index}",
                label=parse_semantic_style_label({"reuse": "rewrite"}),
            )
        )

    profile = persist_semantic_style_example(
        SemanticStyleExample(
            example_id="latest",
            created_at=20,
            bot_id=100,
            group_id=42,
            scene="group_chat",
            trigger_text="前句",
            reply_text="风格样本",
            label=parse_semantic_style_label({"reuse": "style"}),
        )
    )

    assert profile.direct_examples == ["直出 1", "直出 2", "直出 3"]
    assert profile.rewrite_seeds == ["改写 1", "改写 2", "改写 3"]


def test_prune_drops_examples_older_than_ninety_days_and_rebuilds_profiles(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_semantic_style_cache_for_tests()
    now = 100 * 24 * 60 * 60
    old = SemanticStyleExample(
        example_id="old",
        created_at=now - 90 * 24 * 60 * 60 - 1,
        bot_id=100,
        group_id=42,
        scene="group_chat",
        trigger_text="旧前句",
        reply_text="旧接话",
        label=parse_semantic_style_label({"reuse": "direct"}),
    )
    current = old.model_copy(update={"example_id": "current", "created_at": now - 1, "reply_text": "新接话"})
    persist_semantic_style_example(old)
    profile = persist_semantic_style_example(current)

    retained = prune_semantic_style_examples(now=now)

    assert retained == 1
    assert profile.sample_count == 2
    assert build_cached_semantic_style_block(100, 42, "group_chat").endswith("新接话")


def test_positive_bot_style_outcomes_require_human_reply_and_promote_after_recent_threshold(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_semantic_style_cache_for_tests()
    now = 200 * 24 * 60 * 60
    example = SemanticStyleExample(
        example_id="bot:0",
        created_at=now,
        bot_id=100,
        group_id=43,
        scene="group_chat",
        trigger_text="前句",
        reply_text="bot 接话",
        label=parse_semantic_style_label({"reuse": "rewrite"}),
    )

    assert is_positive_bot_style_outcome(
        reply_created_at=now,
        following_created_at=now + 90,
        following_is_bot=False,
        following_text="哈哈",
    )
    assert not is_positive_bot_style_outcome(
        reply_created_at=now,
        following_created_at=now + 91,
        following_is_bot=False,
        following_text="哈哈",
    )
    assert not is_positive_bot_style_outcome(
        reply_created_at=now,
        following_created_at=now + 1,
        following_is_bot=True,
        following_text="继续",
    )

    persist_semantic_style_example(example)
    first_profile = record_bot_style_outcome(
        example,
        following_created_at=now + 1,
        following_is_bot=False,
        following_text="收到",
    )

    assert first_profile is not None
    assert first_profile.sample_count == 1
    assert first_profile.common_style_sample_count == 0
    assert first_profile.bot_style_sample_count == 1

    for index in range(12):
        old_example = example.model_copy(
            update={"example_id": f"bot:old:{index}", "created_at": now - 15 * 24 * 60 * 60, "group_id": 42}
        )
        persist_semantic_style_example(old_example)
        record_bot_style_outcome(
            old_example,
            following_created_at=now - 15 * 24 * 60 * 60 + 1,
            following_is_bot=False,
            following_text="收到",
        )
    for index in range(8):
        recent_example = example.model_copy(
            update={"example_id": f"bot:recent:{index}", "created_at": now - index, "group_id": 42}
        )
        persist_semantic_style_example(recent_example)
        profile = record_bot_style_outcome(
            recent_example,
            following_created_at=now - index + 1,
            following_is_bot=False,
            following_text="收到",
        )

    assert profile is not None
    assert profile.sample_count == 20
    assert profile.bot_style_sample_count == 20
    assert profile.recent_bot_style_sample_count == 8
    assert profile.bot_style_promoted is True


@pytest.mark.asyncio
async def test_semantic_style_worker_labels_and_persists_relation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    label = parse_semantic_style_label({"reuse": "rewrite", "style_anchor": "短句接梗。"})
    worker = AsyncMock(return_value=label)
    monkeypatch.setattr("pallas.product.llm.repeater_semantic_style.label_semantic_style_with_llm", worker)
    from pallas.product.llm.repeater_semantic_style import handle_repeater_semantic_style

    await handle_repeater_semantic_style({
        "example_id": "42:100:99",
        "bot_id": 99,
        "group_id": 42,
        "scene": "group_chat",
        "trigger_text": "又炸了",
        "reply_text": "没救了",
        "realtime_admitted": True,
    })

    worker.assert_awaited_once_with(trigger_text="又炸了", reply_text="没救了")
    assert "没救了" in build_cached_semantic_style_block(99, 42, "group_chat")


def test_visual_label_keeps_only_four_controlled_fields() -> None:
    from pallas.product.llm.repeater_semantic_style import parse_semantic_style_visual_label

    label = parse_semantic_style_visual_label({
        "subject": "person",
        "action": "reaction",
        "tone": "playful",
        "text": "present",
        "image_url": "https://example.invalid/private.png",
        "raw_bytes": "must not persist",
    })

    assert label.model_dump() == {
        "subject": "person",
        "action": "reaction",
        "tone": "playful",
        "text": "present",
    }


def test_visual_circuit_can_disable_probe_and_recover_without_io() -> None:
    from pallas.product.llm.repeater_semantic_style import (
        SemanticStyleVisualCircuitState,
        record_semantic_style_visual_circuit_failure,
        record_semantic_style_visual_circuit_success,
        semantic_style_visual_circuit_decision,
    )

    disabled = semantic_style_visual_circuit_decision(SemanticStyleVisualCircuitState(), enabled=False, now=100)
    assert disabled.mode == "disabled"

    state = SemanticStyleVisualCircuitState()
    for _ in range(3):
        state = record_semantic_style_visual_circuit_failure(state, now=100)
    assert semantic_style_visual_circuit_decision(state, enabled=True, now=101).mode == "skip"
    assert semantic_style_visual_circuit_decision(state, enabled=True, now=160).mode == "probe"

    recovered = record_semantic_style_visual_circuit_success(state, now=160)
    assert semantic_style_visual_circuit_decision(recovered, enabled=True, now=161).mode == "allow"


@pytest.mark.asyncio
async def test_realtime_image_relation_uses_cached_image_and_never_persists_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    text_label = parse_semantic_style_label({"reuse": "style"})
    visual_label = mod.parse_semantic_style_visual_label({
        "subject": "character",
        "action": "reaction",
        "tone": "playful",
        "text": "absent",
    })
    persist = Mock()
    monkeypatch.setattr(mod, "label_semantic_style_with_llm", AsyncMock(return_value=text_label))
    monkeypatch.setattr(mod, "label_semantic_style_visual_with_cached_image", AsyncMock(return_value=visual_label))
    monkeypatch.setattr(mod, "persist_semantic_style_example", persist)

    await mod.handle_repeater_semantic_style({
        "bot_id": 100,
        "group_id": 42,
        "trigger_text": "前句",
        "reply_text": "接话",
        "image_cq_code": "[CQ:image,file=cache.image]",
        "realtime_admitted": True,
    })

    persisted = persist.call_args.args[0]
    assert persisted.label.visual == visual_label
    assert "cache.image" not in persisted.model_dump_json()
