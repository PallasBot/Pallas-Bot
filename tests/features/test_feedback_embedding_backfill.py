from __future__ import annotations

from pallas.product.llm.feedback_embedding_cache import (
    backfill_feedback_trigger_embeddings,
    clear_feedback_embedding_caches_for_tests,
    collect_recent_feedback_trigger_texts,
    get_cached_trigger_embedding,
)
from pallas.product.llm.knowledge.embedding_provider import clear_embedding_provider_cache
from pallas.product.llm.repeater_feedback import append_feedback_entry, build_feedback_entry


def test_backfill_feedback_trigger_embeddings_fills_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("LLM_EMBEDDING_MODEL", "text-embedding-3-small")
    clear_feedback_embedding_caches_for_tests()
    clear_embedding_provider_cache()
    monkeypatch.setattr(
        "pallas.product.llm.feedback_embedding_cache.prefetch_trigger_embedding",
        lambda *_a, **_k: None,
    )

    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=9,
            user_id=2,
            request_id="bf-1",
            user_text="你好啊朋友",
            reply_text="嗨",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=9,
            user_id=3,
            request_id="bf-2",
            user_text="今天天气不错",
            reply_text="是啊",
        )
    )

    texts = collect_recent_feedback_trigger_texts(limit=10)
    assert "你好啊朋友" in texts
    assert "今天天气不错" in texts
    assert get_cached_trigger_embedding("你好啊朋友") is None

    calls: list[list[str]] = []

    def fake_fetch(texts_in, **kwargs):
        calls.append(list(texts_in))
        return [[float(i), 0.0] for i, _ in enumerate(texts_in)]

    monkeypatch.setattr(
        "pallas.product.llm.feedback_embedding_cache.fetch_embeddings_sync",
        fake_fetch,
    )

    stats = backfill_feedback_trigger_embeddings(limit_texts=10, batch_size=8)
    assert stats["scanned"] >= 2
    assert stats["missing"] >= 2
    assert stats["filled"] >= 2
    assert get_cached_trigger_embedding("你好啊朋友") is not None
    assert calls


def test_backfill_skips_when_provider_is_stub(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_EMBEDDING_PROVIDER", "stub")
    clear_feedback_embedding_caches_for_tests()
    clear_embedding_provider_cache()
    stats = backfill_feedback_trigger_embeddings(limit_texts=10)
    assert stats["skipped_stub"] == 1
