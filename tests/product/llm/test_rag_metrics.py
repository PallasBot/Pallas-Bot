"""RAG 查询级命中计量。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.product.llm.rag_metrics import (
    clear_llm_rag_metrics_for_tests,
    cluster_llm_rag_metrics_snapshot,
    llm_rag_metrics_snapshot,
    merge_llm_rag_snapshots,
    record_rag_query_result,
)

if TYPE_CHECKING:
    import pytest


def test_record_rag_query_hit_and_miss() -> None:
    clear_llm_rag_metrics_for_tests()
    record_rag_query_result(hit=True, documents=[("清空会话", "pallas.bot_faq"), ("多轮记忆", "pallas.bot_faq")])
    record_rag_query_result(hit=False)
    snap = llm_rag_metrics_snapshot(include_persisted=False)
    assert snap["hit_count"] == 1
    assert snap["miss_count"] == 1
    assert snap["skip_count"] == 0
    assert snap["hit_rate"] == 50.0
    assert snap["by_document"]["清空会话"] == 1
    assert snap["by_document"]["多轮记忆"] == 1
    assert snap["by_source"]["pallas.bot_faq"] == 2


def test_record_rag_skip_not_in_hit_rate() -> None:
    from pallas.product.llm.rag_metrics import record_rag_skip

    clear_llm_rag_metrics_for_tests()
    record_rag_skip()
    record_rag_skip()
    record_rag_query_result(hit=True, documents=[("A", "s")])
    snap = llm_rag_metrics_snapshot(include_persisted=False)
    assert snap["skip_count"] == 2
    assert snap["hit_count"] == 1
    assert snap["miss_count"] == 0
    assert snap["hit_rate"] == 100.0


def test_merge_and_cluster_rag_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_rag_metrics_for_tests()
    record_rag_query_result(hit=True, documents=[("A", "src-a")])
    local = llm_rag_metrics_snapshot(include_persisted=False)

    def fake_active() -> bool:
        return True

    def fake_is_hub() -> bool:
        return True

    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", fake_active)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_hub", fake_is_hub)
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.iter_worker_shard_ids",
        lambda max_stale_sec=300.0: [1],
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.read_worker_stats_file",
        lambda shard_id: {
            "llm_rag": {
                "day_key": local["day_key"],
                "hit_count": 2,
                "miss_count": 1,
                "by_document": {"B": 2},
                "by_source": {"src-b": 2},
            }
        },
    )
    merged = cluster_llm_rag_metrics_snapshot()
    assert merged["hit_count"] == 3
    assert merged["miss_count"] == 1
    assert merged["by_document"]["A"] == 1
    assert merged["by_document"]["B"] == 2
    assert merged["source"] == "bot_cluster"

    combined = merge_llm_rag_snapshots([local, {"hit_count": 0, "miss_count": 3, "by_document": {}}])
    assert combined["hit_count"] == 1
    assert combined["miss_count"] == 3
    assert combined["hit_rate"] == 25.0


def test_rag_flush_does_not_double_count(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import rag_metrics as rm

    clear_llm_rag_metrics_for_tests()
    path = tmp_path / "llm_rag_stats.json"
    monkeypatch.setattr(rm, "stats_file_path", lambda: path)

    record_rag_query_result(hit=True, documents=[("doc", "src")])
    record_rag_query_result(hit=False)
    rm.flush_rag_stats_sync()
    rm.flush_rag_stats_sync()
    snap = llm_rag_metrics_snapshot(include_persisted=True)
    assert snap["hit_count"] == 1
    assert snap["miss_count"] == 1
    assert snap["by_document"]["doc"] == 1
