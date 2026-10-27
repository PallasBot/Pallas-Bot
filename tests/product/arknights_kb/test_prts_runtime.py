from __future__ import annotations

from pallas.product.arknights_kb import prts_corpus, prts_runtime
from pallas.product.arknights_kb.config import ArknightsKbConfig


def test_runtime_uses_configured_budgets_once_without_changing_download_limits(monkeypatch, tmp_path) -> None:
    cfg = ArknightsKbConfig(
        prts_corpus_packs="references",
        prts_corpus_download_timeout_sec=45,
        prts_corpus_cache_max_mb=24,
        prts_corpus_query_max_mb=40,
    )
    monkeypatch.setattr(prts_runtime, "_STORE", None)
    monkeypatch.setattr(prts_runtime, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(prts_runtime, "get_arknights_kb_config", lambda: cfg)
    download_limits = (
        prts_corpus.MAX_ASSET_COMPRESSED_BYTES,
        prts_corpus.MAX_GENERATION_COMPRESSED_BYTES,
        prts_corpus.MAX_GZIP_UNCOMPRESSED_BYTES,
        prts_corpus.MAX_GENERATION_UNCOMPRESSED_BYTES,
    )
    updates = []
    monkeypatch.setattr(
        prts_runtime,
        "auto_update_if_needed",
        lambda data_dir, pack_ids, *, timeout: updates.append((data_dir, pack_ids, timeout)) or {"updated": False},
    )

    store = prts_runtime.corpus_store()

    assert prts_runtime.corpus_store() is store
    assert store._cache_budget_bytes == 24 * 1024 * 1024
    assert store._query_budget_bytes == 40 * 1024 * 1024
    assert prts_runtime.update_corpus() == {"updated": False}
    assert updates == [(tmp_path, ["references"], 45)]
    assert download_limits == (
        prts_corpus.MAX_ASSET_COMPRESSED_BYTES,
        prts_corpus.MAX_GENERATION_COMPRESSED_BYTES,
        prts_corpus.MAX_GZIP_UNCOMPRESSED_BYTES,
        prts_corpus.MAX_GENERATION_UNCOMPRESSED_BYTES,
    )
