from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.memory.relationship_store import (
    delete_relationship_note,
    is_relationship_store_available,
    list_relationship_notes,
    retrieve_relationship_note,
    save_relationship_note,
)
from pallas.product.llm.memory.store import (
    delete_memory_entry,
    is_llm_memory_store_available,
    list_memory_entries,
    retrieve_memory_hits,
    save_memory_entry,
)


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


@pytest.mark.asyncio
async def test_mongo_memory_save_list_retrieve_delete(beanie_fixture, monkeypatch) -> None:
    clear_llm_config_cache()
    _patch_mongo_backend(monkeypatch)
    cfg = LlmConfig(
        llm_memory_rag_enabled=True,
        llm_vector_retrieve="keyword",
        llm_memory_max_per_group=20,
        llm_memory_rag_top_k=3,
    )
    monkeypatch.setattr("pallas.product.llm.memory.store.get_llm_config", lambda: cfg)
    assert is_llm_memory_store_available() is True

    assert await save_memory_entry(1, 100, "本群周五固定开黑", source="teach", cfg=cfg) is True
    assert await save_memory_entry(1, 100, "银灰是谢拉格军阀", source="teach", cfg=cfg) is True

    rows = await list_memory_entries(1, 100, query="开黑")
    assert len(rows) == 1
    assert "开黑" in rows[0]["content"]
    entry_id = int(rows[0]["id"])

    hits = await retrieve_memory_hits(1, 100, "周五开黑", cfg=cfg)
    assert any("开黑" in str(item.get("content") or "") for item in hits)

    assert await delete_memory_entry(entry_id, bot_id=1) is True
    assert await list_memory_entries(1, 100, query="开黑") == []


@pytest.mark.asyncio
async def test_mongo_relationship_save_retrieve_delete(beanie_fixture, monkeypatch) -> None:
    clear_llm_config_cache()
    _patch_mongo_backend(monkeypatch)
    cfg = LlmConfig(
        llm_relationship_notes_enabled=True,
        llm_relationship_half_life_days=0,
        llm_relationship_min_weight=0.01,
    )
    monkeypatch.setattr("pallas.product.llm.memory.relationship_store.get_llm_config", lambda: cfg)
    assert is_relationship_store_available() is True

    assert await save_relationship_note(1, 100, 200, "是老熟人", source="teach", cfg=cfg) is True
    note = await retrieve_relationship_note(1, 100, 200, cfg=cfg)
    assert note == "是老熟人"

    rows = await list_relationship_notes(1, 100)
    assert len(rows) == 1
    note_id = int(rows[0]["id"])
    assert await delete_relationship_note(note_id, bot_id=1) is True
    assert await retrieve_relationship_note(1, 100, 200, cfg=cfg) is None
