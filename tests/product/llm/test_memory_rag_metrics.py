"""群记忆 RAG 计量。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.product.llm.memory_rag_metrics import (
    clear_llm_memory_rag_metrics_for_tests,
    flush_memory_rag_stats_sync,
    llm_memory_rag_metrics_snapshot,
    record_memory_rag_query_result,
)

if TYPE_CHECKING:
    import pytest


def test_record_memory_rag_hit_and_miss() -> None:
    clear_llm_memory_rag_metrics_for_tests()
    record_memory_rag_query_result(hit=True, documents=[("旧事A", "memory")])
    record_memory_rag_query_result(hit=False)
    snap = llm_memory_rag_metrics_snapshot(include_persisted=False)
    assert snap["hit_count"] == 1
    assert snap["miss_count"] == 1
    assert snap["by_source"]["memory"] == 1


def test_memory_rag_flush_does_not_double(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import memory_rag_metrics as mm

    clear_llm_memory_rag_metrics_for_tests()
    path = tmp_path / "llm_memory_rag_stats.json"
    monkeypatch.setattr(mm, "stats_file_path", lambda: path)
    record_memory_rag_query_result(hit=True, documents=[("x", "memory")])
    flush_memory_rag_stats_sync()
    flush_memory_rag_stats_sync()
    snap = llm_memory_rag_metrics_snapshot(include_persisted=True)
    assert snap["hit_count"] == 1
