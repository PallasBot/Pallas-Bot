"""observe 关系正文离线清理：dry-run 只统计、teach 不动、仅删违规分段、幂等。"""

from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache


def _patch_mongo_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.foundation.db.runtime.is_postgresql_backend",
        lambda _backend=None: False,
    )
    monkeypatch.setattr(
        "pallas.core.foundation.db.runtime.is_mongodb_backend",
        lambda _backend=None: True,
    )
    monkeypatch.setattr(
        "pallas.core.foundation.db.runtime_storage_ready",
        lambda _backend=None: True,
    )


async def _seed_note(
    note_id: int,
    content: str,
    source: str,
    *,
    bot_id: int = 1,
    group_id: int = 100,
    warmth_delta: float = 0.0,
    assertiveness_delta: float = 0.0,
    affinity: float = 0.0,
    weight: float = 1.0,
) -> None:
    from pallas.core.foundation.db.modules import LlmRelationshipNote

    await LlmRelationshipNote(
        note_id=note_id,
        bot_id=bot_id,
        group_id=group_id,
        user_id=note_id * 10,
        content=content,
        source=source,
        weight=weight,
        warmth_delta=warmth_delta,
        assertiveness_delta=assertiveness_delta,
        affinity=affinity,
        created_at=1,
        updated_at=1,
    ).insert()


async def _fetch_content(note_id: int) -> str:
    from pallas.core.foundation.db.modules import LlmRelationshipNote

    row = await LlmRelationshipNote.find_one({"note_id": note_id})
    return str(row.content or "") if row is not None else ""


@pytest.fixture
def cleanup_env(beanie_fixture, monkeypatch: pytest.MonkeyPatch):
    clear_llm_config_cache()
    _patch_mongo_backend(monkeypatch)
    cfg = LlmConfig(llm_relationship_notes_enabled=True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.relationship_store.get_llm_config",
        lambda: cfg,
    )
    return cfg


@pytest.mark.asyncio
async def test_cleanup_dry_run_reports_without_writing(cleanup_env) -> None:
    from pallas.product.llm.memory.relationship_store import (
        cleanup_observed_relationship_facts,
        is_relationship_store_available,
    )

    assert is_relationship_store_available() is True
    await _seed_note(1, "该用户名叫小明；可能依赖牛牛回复", "observe")
    stats = await cleanup_observed_relationship_facts(bot_id=1, group_id=100, dry_run=True, cfg=cleanup_env)
    assert stats["rows"] == 1
    assert stats["changed_rows"] == 1
    assert stats["removed_parts"] == 1
    assert stats["dry_run"] is True
    assert await _fetch_content(1) == "该用户名叫小明；可能依赖牛牛回复"


@pytest.mark.asyncio
async def test_cleanup_keeps_teach_rows_untouched(cleanup_env) -> None:
    from pallas.product.llm.memory.relationship_store import cleanup_observed_relationship_facts

    await _seed_note(1, "可能依赖牛牛回复", "teach")
    await _seed_note(2, "似乎在闹脾气", "observe")
    stats = await cleanup_observed_relationship_facts(bot_id=1, group_id=100, dry_run=False, cfg=cleanup_env)
    assert stats["rows"] == 1
    assert stats["changed_rows"] == 1
    assert await _fetch_content(1) == "可能依赖牛牛回复"

    from pallas.core.foundation.db.modules import LlmRelationshipNote

    teach = await LlmRelationshipNote.find_one({"note_id": 1})
    assert str(teach.source or "") == "teach"


@pytest.mark.asyncio
async def test_cleanup_removes_only_bad_parts_and_keeps_order(cleanup_env) -> None:
    from pallas.product.llm.memory.relationship_store import cleanup_observed_relationship_facts

    await _seed_note(1, "该用户名叫小明；可能依赖牛牛回复；是本群群主", "observe")
    stats = await cleanup_observed_relationship_facts(bot_id=1, group_id=100, dry_run=False, cfg=cleanup_env)
    assert stats["removed_parts"] == 1
    assert await _fetch_content(1) == "该用户名叫小明；是本群群主"


@pytest.mark.asyncio
async def test_cleanup_keeps_same_slot_admissible_parts(cleanup_env) -> None:
    """清理只删违规分段：两个同槽合格段不得被槽位覆盖吞掉。"""
    from pallas.product.llm.memory.relationship_store import cleanup_observed_relationship_facts

    await _seed_note(1, "希望被叫作队长；可能依赖牛牛回复；希望被叫作小明", "observe")
    stats = await cleanup_observed_relationship_facts(bot_id=1, group_id=100, dry_run=False, cfg=cleanup_env)
    assert stats["removed_parts"] == 1
    assert await _fetch_content(1) == "希望被叫作队长；希望被叫作小明"


@pytest.mark.asyncio
async def test_cleanup_keeps_all_admissible_parts_beyond_merge_cap(cleanup_env) -> None:
    """清理只删违规分段：合格段超过 merge 上限时也不得被截断。"""
    from pallas.product.llm.memory.relationship_store import cleanup_observed_relationship_facts

    good = [f"事实编号{chr(97 + i)}" for i in range(8)]
    await _seed_note(1, "；".join(good) + "；可能依赖牛牛回复", "observe")
    stats = await cleanup_observed_relationship_facts(bot_id=1, group_id=100, dry_run=False, cfg=cleanup_env)
    assert stats["removed_parts"] == 1
    assert await _fetch_content(1) == "；".join(good)


@pytest.mark.asyncio
async def test_cleanup_is_idempotent(cleanup_env) -> None:
    from pallas.product.llm.memory.relationship_store import cleanup_observed_relationship_facts

    await _seed_note(1, "该用户名叫小明；可能依赖牛牛回复", "observe")
    first = await cleanup_observed_relationship_facts(bot_id=1, group_id=100, dry_run=False, cfg=cleanup_env)
    second = await cleanup_observed_relationship_facts(bot_id=1, group_id=100, dry_run=False, cfg=cleanup_env)
    assert first["changed_rows"] == 1
    assert second["changed_rows"] == 0
    assert second["removed_parts"] == 0
    assert await _fetch_content(1) == "该用户名叫小明"


@pytest.mark.asyncio
async def test_cleanup_clears_content_but_keeps_row_and_numeric_fields(cleanup_env) -> None:
    from pallas.core.foundation.db.modules import LlmRelationshipNote
    from pallas.product.llm.memory.relationship_store import cleanup_observed_relationship_facts

    await _seed_note(
        1,
        "可能依赖牛牛回复；似乎在闹脾气",
        "observe",
        warmth_delta=0.05,
        assertiveness_delta=-0.05,
        affinity=0.35,
        weight=0.8,
    )
    stats = await cleanup_observed_relationship_facts(bot_id=1, group_id=100, dry_run=False, cfg=cleanup_env)
    assert stats["changed_rows"] == 1
    assert stats["removed_parts"] == 2
    row = await LlmRelationshipNote.find_one({"note_id": 1})
    assert row is not None
    assert str(row.content or "") == ""
    assert str(row.source or "") == "observe"
    assert float(row.affinity) == 0.35
    assert float(row.warmth_delta) == 0.05
    assert float(row.assertiveness_delta) == -0.05
    assert float(row.weight) == 0.8


@pytest.mark.asyncio
async def test_cleanup_scopes_to_bot_and_group(cleanup_env) -> None:
    from pallas.product.llm.memory.relationship_store import cleanup_observed_relationship_facts

    await _seed_note(1, "可能依赖牛牛回复", "observe", bot_id=2)
    await _seed_note(2, "可能依赖牛牛回复", "observe", group_id=200)
    stats = await cleanup_observed_relationship_facts(bot_id=1, group_id=100, dry_run=False, cfg=cleanup_env)
    assert stats["rows"] == 0
    assert stats["changed_rows"] == 0
    assert await _fetch_content(1) == "可能依赖牛牛回复"
    assert await _fetch_content(2) == "可能依赖牛牛回复"
