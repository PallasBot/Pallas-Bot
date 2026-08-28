from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.embedding_client import (
    embedding_capability_trace,
    fetch_embeddings_sync,
    parse_embeddings_response,
)
from pallas.product.llm.knowledge.vector_backend import effective_vector_retrieve_mode


@pytest.fixture(autouse=True)
def _reset_embedding_error() -> None:
    yield
    from pallas.product.llm.knowledge import embedding_client

    embedding_client._last_embedding_error = ""


def test_parse_embeddings_response_sorts_by_index() -> None:
    payload = {
        "data": [
            {"index": 1, "embedding": [0.2, 0.8]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ]
    }
    vectors = parse_embeddings_response(payload)
    assert vectors == [[1.0, 0.0], [0.2, 0.8]]


def test_stub_embedding_forces_keyword_retrieve() -> None:
    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="stub", llm_vector_retrieve="hybrid")

    assert effective_vector_retrieve_mode(cfg) == "keyword"


def test_fetch_embeddings_uses_openai_compatible_endpoint(monkeypatch) -> None:
    from pallas.product.llm.knowledge.embedding_provider import clear_embedding_provider_cache

    clear_embedding_provider_cache()
    cfg = LlmConfig(
        llm_embedding_model="text-embedding-3-small",
        llm_embedding_provider="openai",
        llm_base_url="https://example.test",
        llm_api_key="key",
    )

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [1.0, 2.0]}]}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: Response())

    assert fetch_embeddings_sync(["hello"], cfg=cfg) == [[1.0, 2.0]]


def test_fetch_embeddings_failure_uses_stub(monkeypatch) -> None:
    from pallas.product.llm.knowledge.embedding_provider import clear_embedding_provider_cache

    clear_embedding_provider_cache()
    cfg = LlmConfig(
        llm_embedding_model="text-embedding-3-small",
        llm_embedding_provider="openai",
        llm_base_url="https://example.test",
    )
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")))

    vectors = fetch_embeddings_sync(["hello"], cfg=cfg)

    assert vectors is not None
    assert embedding_capability_trace(cfg)["embedding_fallback"] is True
    assert effective_vector_retrieve_mode(cfg) == "keyword"


def test_fetch_embeddings_failure_skips_stub_when_opt_out(monkeypatch) -> None:
    from pallas.product.llm.knowledge.embedding_provider import clear_embedding_provider_cache

    clear_embedding_provider_cache()
    cfg = LlmConfig(
        llm_embedding_model="text-embedding-3-small",
        llm_embedding_provider="openai",
        llm_base_url="https://example.test",
    )
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")))

    assert fetch_embeddings_sync(["hello"], cfg=cfg, fallback_stub=False) is None
