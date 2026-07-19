"""hybrid RAG：可插拔 vector 检索后端。"""

from __future__ import annotations

import pytest

from pallas.product.llm.knowledge.declare import knowledge_source_row
from pallas.product.llm.knowledge.embedding_score import cosine_similarity, embedding_relevance_score
from pallas.product.llm.knowledge.metadata import parse_knowledge_source_decl
from pallas.product.llm.knowledge.vector_backend import (
    EmbeddingAugmentedBackend,
    KeywordVectorBackend,
    blend_hybrid_score,
    get_vector_retrieve_backend,
    retrieve_chunks_embedding,
    set_vector_retrieve_backend,
    vector_retrieve_mode,
)


@pytest.fixture(autouse=True)
def reset_backend():
    set_vector_retrieve_backend(None)
    yield
    set_vector_retrieve_backend(None)


def _sample_decl():
    row = knowledge_source_row(
        source_id="test.faq",
        title="Test FAQ",
        description="demo",
        chunks=[
            {"title": "用法", "content": "帮助说明", "keywords": "帮助,用法"},
            {"title": "清空", "content": "会话清空步骤", "keywords": "清空,会话"},
        ],
    )
    decl = parse_knowledge_source_decl(row)
    assert decl is not None
    return decl


def test_cosine_similarity_identical_vectors() -> None:
    vec = [1.0, 0.0, -1.0]
    assert cosine_similarity(vec, vec) == pytest.approx(1.0)
    assert embedding_relevance_score(vec, vec) == 100


def test_keyword_backend_retrieves_by_keyword() -> None:
    backend = KeywordVectorBackend()
    chunks = backend.retrieve(_sample_decl(), "帮助", top_k=3, max_chunk_len=200)
    assert len(chunks) == 1
    assert "帮助" in chunks[0].content or "用法" in chunks[0].title


def test_embedding_backend_falls_back_when_api_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode",
        lambda: "embedding",
    )
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.fetch_embeddings_sync",
        lambda *_args, **_kwargs: None,
    )
    backend = EmbeddingAugmentedBackend()
    chunks = backend.retrieve(_sample_decl(), "帮助", top_k=3, max_chunk_len=200)
    assert len(chunks) == 1


def test_embedding_backend_ranks_by_vector_similarity(monkeypatch: pytest.MonkeyPatch) -> None:
    decl = _sample_decl()

    def fake_vectors(texts, **_kwargs):
        vectors = []
        for text in texts:
            if "帮助" in text:
                vectors.append([1.0, 0.0])
            elif "清空" in text:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([0.5, 0.5])
        return vectors

    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.fetch_embeddings_sync",
        fake_vectors,
    )
    hits = retrieve_chunks_embedding(decl, "帮助说明", top_k=2, max_chunk_len=200, mode="embedding")
    assert hits is not None
    assert hits[0].title == "用法"


def test_hybrid_backend_blends_keyword_and_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    decl = _sample_decl()

    def fake_vectors(texts, **_kwargs):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.fetch_embeddings_sync",
        fake_vectors,
    )
    hits = retrieve_chunks_embedding(decl, "帮助", top_k=2, max_chunk_len=200, mode="hybrid")
    assert hits is not None
    assert len(hits) >= 1
    assert blend_hybrid_score(embedding_score=80, keyword_score=10) >= 80


def test_get_vector_retrieve_backend_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.config.repo_env_raw_value",
        lambda key: "embedding" if key == "LLM_VECTOR_RETRIEVE" else None,
    )
    backend = get_vector_retrieve_backend()
    assert isinstance(backend, EmbeddingAugmentedBackend)
    assert vector_retrieve_mode() == "embedding"
