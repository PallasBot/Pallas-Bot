from __future__ import annotations

import json

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.feedback_embedding_cache import (
    backfill_feedback_trigger_embeddings,
    clear_feedback_embedding_caches_for_tests,
    collect_recent_feedback_trigger_texts,
    ensure_trigger_cache_loaded,
    feedback_trigger_cache_stats,
    get_cached_trigger_embedding,
    trigger_embeddings_path,
)
from pallas.product.llm.knowledge.embedding_client import (
    embedding_model_name,
    resolved_embedding_model_name,
)
from pallas.product.llm.knowledge.embedding_provider import clear_embedding_provider_cache
from pallas.product.llm.repeater_feedback import append_feedback_entry, build_feedback_entry

_LOCAL_DEFAULT = "BAAI/bge-small-zh-v1.5"


def test_resolved_embedding_model_name_local_defaults_from_stub() -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="local")
    assert embedding_model_name(cfg) == "stub"
    assert resolved_embedding_model_name(cfg) == _LOCAL_DEFAULT


def test_trigger_cache_skips_stub_disk_when_local_resolved_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("LLM_EMBEDDING_MODEL", "stub")
    clear_llm_config_cache()
    clear_feedback_embedding_caches_for_tests()
    clear_embedding_provider_cache()

    path = trigger_embeddings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": "stub",
                "items": {"deadbeef": {"vec": [0.1] * 16}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    model = ensure_trigger_cache_loaded()
    stats = feedback_trigger_cache_stats()
    assert model == _LOCAL_DEFAULT
    assert stats["cached"] == 0
    assert stats["model"] == _LOCAL_DEFAULT


def test_backfill_feedback_trigger_embeddings_fills_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_feedback_embedding_caches_for_tests()
    clear_embedding_provider_cache()
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_provider.resolve_embedding_provider_name",
        lambda cfg=None: "openai",
    )
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
    clear_feedback_embedding_caches_for_tests()
    clear_embedding_provider_cache()
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_provider.resolve_embedding_provider_name",
        lambda cfg=None: "stub",
    )
    stats = backfill_feedback_trigger_embeddings(limit_texts=10)
    assert stats["skipped_stub"] == 1
