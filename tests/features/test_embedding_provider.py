from __future__ import annotations

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.embedding_client import (
    embedding_capability_trace,
    fetch_embeddings_sync,
)
from pallas.product.llm.knowledge.embedding_provider import (
    OpenAICompatibleEmbeddingProvider,
    StubEmbeddingProvider,
    clear_embedding_provider_cache,
    get_embedding_provider,
    list_embedding_provider_names,
    resolve_embedding_provider_name,
)


def test_resolve_provider_name_infers_stub_from_model() -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="stub")
    assert resolve_embedding_provider_name(cfg) == "stub"
    assert isinstance(get_embedding_provider(cfg), StubEmbeddingProvider)


def test_resolve_provider_name_openai_when_model_set(monkeypatch) -> None:
    clear_embedding_provider_cache()
    monkeypatch.delenv("LLM_EMBEDDING_PROVIDER", raising=False)
    cfg = LlmConfig(llm_embedding_model="text-embedding-3-small")
    assert resolve_embedding_provider_name(cfg) == "openai"
    assert isinstance(get_embedding_provider(cfg), OpenAICompatibleEmbeddingProvider)


def test_resolve_provider_name_env_override(monkeypatch) -> None:
    clear_embedding_provider_cache()
    monkeypatch.setenv("LLM_EMBEDDING_PROVIDER", "stub")
    cfg = LlmConfig(llm_embedding_model="text-embedding-3-small")
    assert resolve_embedding_provider_name(cfg) == "stub"
    assert isinstance(get_embedding_provider(cfg), StubEmbeddingProvider)


def test_resolve_provider_name_from_cfg_field() -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="text-embedding-3-small", llm_embedding_provider="stub")
    assert resolve_embedding_provider_name(cfg) == "stub"
    assert isinstance(get_embedding_provider(cfg), StubEmbeddingProvider)


def test_list_embedding_provider_names() -> None:
    assert list_embedding_provider_names() == ["stub", "openai", "local"]


def test_resolve_provider_name_local(monkeypatch) -> None:
    clear_embedding_provider_cache()
    monkeypatch.setenv("LLM_EMBEDDING_PROVIDER", "local")
    cfg = LlmConfig(llm_embedding_model="stub")
    assert resolve_embedding_provider_name(cfg) == "local"
    from pallas.product.llm.knowledge.embedding_provider import LocalFastEmbedProvider

    assert isinstance(get_embedding_provider(cfg), LocalFastEmbedProvider)


def test_build_embedding_status_stub() -> None:
    clear_embedding_provider_cache()
    from pallas.product.llm.knowledge.embedding_provider import build_embedding_status

    status = build_embedding_status(probe=False)
    assert status["embedding_provider"] == "stub"
    assert status["semantic_available"] is False
    assert "local" in status["available_providers"]
    assert status["probe_ok"] is None


def test_capability_trace_includes_provider() -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="stub")
    trace = embedding_capability_trace(cfg)
    assert trace["embedding_provider"] == "stub"
    assert trace["semantic_available"] is False


def test_fetch_via_provider_openai(monkeypatch) -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(
        llm_embedding_model="text-embedding-3-small",
        llm_base_url="https://example.test",
        llm_api_key="key",
    )

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.5, 0.5]}]}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: Response())
    assert fetch_embeddings_sync(["hello"], cfg=cfg) == [[0.5, 0.5]]
    assert embedding_capability_trace(cfg)["embedding_provider"] == "openai"
