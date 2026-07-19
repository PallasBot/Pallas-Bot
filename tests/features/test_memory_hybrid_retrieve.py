"""记忆检索 hybrid RAG。"""

from __future__ import annotations

import pytest

from pallas.product.llm.memory.retrieve import (
    memory_relevance_score,
    parse_cached_embedding,
    rank_memory_candidates,
)


def test_rank_memory_candidates_keyword_mode() -> None:
    rows = rank_memory_candidates(
        "牛牛喜欢摸鱼",
        [
            {"keywords": "摸鱼,休息", "content": "群里常说摸鱼"},
            {"keywords": "加班", "content": "周末要加班"},
        ],
        mode="keyword",
    )
    assert rows
    assert "摸鱼" in rows[0]["content"] or "摸鱼" in rows[0]["keywords"]


def test_rank_memory_candidates_embedding_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.fetch_embeddings_sync",
        lambda *_args, **_kwargs: None,
    )
    rows = rank_memory_candidates(
        "摸鱼",
        [{"keywords": "摸鱼", "content": "今天摸鱼"}],
        mode="embedding",
    )
    assert len(rows) == 1
    assert rows[0]["score"] == memory_relevance_score("摸鱼", keywords="摸鱼", content="今天摸鱼")


def test_rank_memory_candidates_hybrid_prefers_embedding(monkeypatch) -> None:
    def fake_vectors(texts, **_kwargs):
        vectors = []
        for text in texts:
            if "摸鱼" in text:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors

    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.fetch_embeddings_sync",
        fake_vectors,
    )
    rows = rank_memory_candidates(
        "摸鱼话题",
        [
            {"keywords": "摸鱼", "content": "摸鱼快乐"},
            {"keywords": "加班", "content": "周末加班"},
        ],
        mode="hybrid",
    )
    assert rows[0]["keywords"] == "摸鱼"


def test_rank_memory_candidates_uses_cached_embedding(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_vectors(texts, **_kwargs):
        calls.append(list(texts))
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.fetch_embeddings_sync",
        fake_vectors,
    )
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.embedding_model_name",
        lambda _cfg=None: "stub",
    )
    rows = rank_memory_candidates(
        "摸鱼",
        [
            {
                "id": 1,
                "keywords": "摸鱼",
                "content": "今天摸鱼",
                "embedding": [1.0, 0.0],
                "embedding_model": "stub",
            },
            {
                "id": 2,
                "keywords": "加班",
                "content": "周末加班",
                "embedding_model": "stub",
            },
        ],
        mode="hybrid",
        embedding_model="stub",
    )
    assert calls
    # query + 缺缓存的「加班」；已缓存的「摸鱼」不再送入
    assert len(calls[0]) == 2
    assert rows[0]["keywords"] == "摸鱼"
    by_id = {item["id"]: item for item in rows}
    assert not by_id[1].get("embedding_dirty")
    assert by_id[2].get("embedding_dirty") is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
        ("[1.0, 2.0, 3.0]", [1.0, 2.0, 3.0]),
        (["not-a-number", {}], None),
        ("[1.0, 2.0", None),
        ({"embedding": [0.1, 0.2]}, None),
        (42, None),
        (None, None),
        ("", None),
    ],
)
def test_parse_cached_embedding_edge_cases(raw, expected) -> None:
    assert parse_cached_embedding(raw) == expected


def test_rank_memory_candidates_treats_model_mismatch_as_uncached(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_vectors(texts, **_kwargs):
        calls.append(list(texts))
        return [[0.5, 0.5] for _ in texts]

    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.fetch_embeddings_sync",
        fake_vectors,
    )
    ranked = rank_memory_candidates(
        "摸鱼",
        [
            {
                "id": 1,
                "keywords": "摸鱼",
                "content": "cached different model",
                "embedding_model": "other-model",
                "embedding_json": "[0.5, 0.5]",
            }
        ],
        mode="hybrid",
        embedding_model="target-model",
    )
    assert calls
    assert any("cached different model" in text for text in calls[0])
    assert ranked[0].get("embedding_dirty") is True


def test_rank_memory_candidates_parses_stringified_embedding_json(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_vectors(texts, **_kwargs):
        calls.append(list(texts))
        return [[0.1, 0.9] for _ in texts]

    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.fetch_embeddings_sync",
        fake_vectors,
    )
    ranked = rank_memory_candidates(
        "摸鱼",
        [
            {
                "id": 1,
                "keywords": "摸鱼",
                "content": "cached stringified",
                "embedding_model": "test-model",
                "embedding_json": "[0.1, 0.9]",
            }
        ],
        mode="hybrid",
        embedding_model="test-model",
    )
    # query only；命中缓存的条目不再送入
    assert calls == [["摸鱼"]]
    assert not ranked[0].get("embedding_dirty")


def test_default_vector_retrieve_is_hybrid(monkeypatch) -> None:
    from pallas.product.llm import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "repo_env_raw_value", lambda _key: None)
    cfg_mod.clear_llm_config_cache()
    assert cfg_mod.resolve_llm_vector_retrieve() == "hybrid"
