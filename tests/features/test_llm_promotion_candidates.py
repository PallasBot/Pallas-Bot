from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.config import clear_llm_config_cache
from pallas.product.llm.promotion_candidates import (
    PROMOTION_SUPPORT_THRESHOLD,
    PromotionCandidate,
    auto_promote_eligible_candidates_for_group,
    build_candidate_id,
    list_promotion_candidates,
    refresh_promotion_candidates_for_group,
    resolve_promotion_candidate,
    resolve_promotion_candidate_with_writeback,
    writeback_promotion_candidate,
)
from pallas.product.llm.repeater_feedback import (
    append_feedback_entry,
    build_feedback_entry,
    group_feedback_bias_snapshot,
)


def enable_writeback_env(monkeypatch) -> None:
    def fake_raw(key: str):
        values = {
            "LLM_CHAT_ENABLED": "true",
            "LLM_REPEATER_FEEDBACK_ENABLED": "true",
            "LLM_REPEATER_WRITEBACK_ENABLED": "true",
        }
        return values.get(str(key or "").strip().upper())

    monkeypatch.setattr("pallas.product.llm.config.repo_env_raw_value", fake_raw)
    clear_llm_config_cache()


def test_build_candidate_id_is_stable() -> None:
    assert build_candidate_id(group_id=123, trigger_text="你又来这套", reply_text="少来。") == build_candidate_id(
        group_id=123,
        trigger_text="你又来这套",
        reply_text="少来。",
    )
    assert build_candidate_id(group_id=123, trigger_text="你又来这套", reply_text="少来。") != build_candidate_id(
        group_id=124,
        trigger_text="你又来这套",
        reply_text="少来。",
    )


def test_refresh_promotion_candidates_requires_writeback_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "pallas.product.llm.config.repo_env_raw_value",
        lambda _key: None,
    )
    clear_llm_config_cache()

    created = refresh_promotion_candidates_for_group(group_id=123)

    assert created == []


def test_refresh_promotion_candidates_builds_pending_candidate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    enable_writeback_env(monkeypatch)

    for idx in range(PROMOTION_SUPPORT_THRESHOLD):
        append_feedback_entry(
            build_feedback_entry(
                bot_id=10001,
                group_id=123,
                user_id=456 + idx,
                request_id=f"req-{idx}",
                user_text="你又来这套",
                reply_text="少来。",
                behavior_scene="banter",
            )
        )

    rows = list_promotion_candidates(group_id=123, refresh=False)

    assert len(rows) == 1
    assert rows[0].reply_text == "少来。"
    assert rows[0].support_count == PROMOTION_SUPPORT_THRESHOLD
    assert rows[0].promoted is False
    assert rows[0].rejected_reason == ""


def test_group_feedback_bias_snapshot_includes_promotion_candidate_count(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    enable_writeback_env(monkeypatch)

    for idx in range(PROMOTION_SUPPORT_THRESHOLD):
        append_feedback_entry(
            build_feedback_entry(
                bot_id=10001,
                group_id=123,
                user_id=456 + idx,
                request_id=f"req-{idx}",
                user_text="你又来这套",
                reply_text="少来。",
                behavior_scene="banter",
            )
        )

    snap = group_feedback_bias_snapshot(group_id=123, limit=50)

    assert snap["promotion_candidate_count"] == 1


def test_resolve_promotion_candidate_promote_and_reject(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    enable_writeback_env(monkeypatch)

    for idx in range(PROMOTION_SUPPORT_THRESHOLD):
        append_feedback_entry(
            build_feedback_entry(
                bot_id=10001,
                group_id=123,
                user_id=456 + idx,
                request_id=f"req-{idx}",
                user_text="你又来这套",
                reply_text="少来。",
                behavior_scene="banter",
            )
        )
    rows = list_promotion_candidates(group_id=123, refresh=False)
    candidate_id = rows[0].candidate_id

    promoted = resolve_promotion_candidate(candidate_id, action="promote")
    assert promoted is not None
    assert promoted.promoted is True

    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=999,
            request_id="req-new",
            user_text="你先别急",
            reply_text="行吧。",
            behavior_scene="venting",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=998,
            request_id="req-new-2",
            user_text="你先别急",
            reply_text="行吧。",
            behavior_scene="venting",
        )
    )
    rows = list_promotion_candidates(group_id=123, include_resolved=True, refresh=False)
    pending = next(row for row in rows if row.reply_text == "行吧。")
    rejected = resolve_promotion_candidate(pending.candidate_id, action="reject", reason="too generic")
    assert rejected is not None
    assert rejected.promoted is False
    assert rejected.rejected_reason == "too generic"

    pending_rows = list_promotion_candidates(group_id=123, refresh=False)
    assert all(row.reply_text != "行吧。" for row in pending_rows)


@pytest.mark.asyncio
async def test_resolve_promotion_candidate_with_writeback_persists_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    enable_writeback_env(monkeypatch)

    for idx in range(PROMOTION_SUPPORT_THRESHOLD):
        append_feedback_entry(
            build_feedback_entry(
                bot_id=10001,
                group_id=123,
                user_id=456 + idx,
                request_id=f"req-{idx}",
                user_text="你又来这套",
                reply_text="少来。",
                behavior_scene="banter",
            )
        )
    rows = list_promotion_candidates(group_id=123, refresh=False)
    candidate_id = rows[0].candidate_id

    fake_repo = SimpleNamespace(
        learn_answer=AsyncMock(),
        context_exists_by_keywords=AsyncMock(return_value=False),
        upsert_answer=AsyncMock(),
        insert=AsyncMock(),
    )
    monkeypatch.setattr(
        "pallas.core.foundation.db.context_repo_access.get_shared_context_repository",
        lambda: fake_repo,
    )
    monkeypatch.setattr("pallas.core.foundation.db.is_postgresql_backend", lambda: False)

    updated = await resolve_promotion_candidate_with_writeback(candidate_id, action="promote")

    assert updated is not None
    assert updated.promoted is True
    assert updated.writeback_status == "written"
    assert updated.writeback_at > 0
    fake_repo.learn_answer.assert_awaited_once()

    resolved = list_promotion_candidates(group_id=123, include_resolved=True, refresh=False)[0]
    assert resolved.writeback_status == "written"


def test_refresh_promotion_candidates_aggregates_corrected_reply_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    enable_writeback_env(monkeypatch)

    append_feedback_entry(
        build_feedback_entry(
            bot_id=10001,
            group_id=123,
            user_id=456,
            request_id="req-corr-only",
            user_text="你好",
            reply_text="嗨。",
            corrected_reply_text="你好呀，在呢",
            corrected_at=1,
        )
    )

    rows = list_promotion_candidates(group_id=123, refresh=False)

    assert len(rows) == 1
    assert rows[0].reply_text == "你好呀，在呢"
    assert rows[0].support_count == 2
    assert rows[0].correction_backed is True


@pytest.mark.asyncio
async def test_auto_promote_eligible_candidates_writes_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    enable_writeback_env(monkeypatch)

    for idx in range(3):
        append_feedback_entry(
            build_feedback_entry(
                bot_id=10001,
                group_id=123,
                user_id=456 + idx,
                request_id=f"req-auto-{idx}",
                user_text="你又来这套",
                reply_text="少来。",
                behavior_scene="banter",
            )
        )

    fake_repo = SimpleNamespace(
        learn_answer=AsyncMock(),
        context_exists_by_keywords=AsyncMock(return_value=False),
        upsert_answer=AsyncMock(),
        insert=AsyncMock(),
    )
    monkeypatch.setattr(
        "pallas.core.foundation.db.context_repo_access.get_shared_context_repository",
        lambda: fake_repo,
    )
    monkeypatch.setattr("pallas.core.foundation.db.is_postgresql_backend", lambda: False)

    promoted = await auto_promote_eligible_candidates_for_group(group_id=123)

    assert len(promoted) == 1
    assert promoted[0].promoted is True
    assert promoted[0].writeback_status == "written"
    assert promoted[0].writeback_message == "auto_promoted"
    fake_repo.learn_answer.assert_awaited_once()
    pending = list_promotion_candidates(group_id=123, refresh=False)
    assert pending == []


@pytest.mark.asyncio
async def test_writeback_promotion_candidate_blocks_contaminated_reply(monkeypatch) -> None:
    from pallas.product.llm.config import LlmConfig

    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_corpus_learn_guard_enabled=True),
    )
    monkeypatch.setattr("pallas.core.foundation.db.is_postgresql_backend", lambda: False)
    candidate = PromotionCandidate(
        candidate_id="bad-celebration",
        group_id=123,
        trigger_text="晚安",
        reply_text="希望每个庆典都能顺利举行",
    )
    updated = await writeback_promotion_candidate(candidate)
    assert updated.writeback_status == "failed"
    assert updated.writeback_message == "corpus contamination guard"
