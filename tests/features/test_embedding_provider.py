from __future__ import annotations

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.embedding_client import (
    embedding_capability_trace,
    fetch_embeddings_sync,
)
from pallas.product.llm.knowledge.embedding_provider import (
    LocalFastEmbedProvider,
    OpenAICompatibleEmbeddingProvider,
    StubEmbeddingProvider,
    clear_embedding_provider_cache,
    get_embedding_provider,
    list_embedding_provider_names,
    resolve_embedding_provider_name,
    resolve_remote_embedding_model,
)


def test_resolve_provider_name_infers_stub_from_model() -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="")
    assert resolve_embedding_provider_name(cfg) == "stub"
    assert isinstance(get_embedding_provider(cfg), StubEmbeddingProvider)


def test_resolve_provider_name_openai_when_model_set() -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="text-embedding-3-small", llm_embedding_provider="")
    assert resolve_embedding_provider_name(cfg) == "openai"
    assert isinstance(get_embedding_provider(cfg), OpenAICompatibleEmbeddingProvider)


def test_resolve_provider_name_from_cfg_field() -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="text-embedding-3-small", llm_embedding_provider="stub")
    assert resolve_embedding_provider_name(cfg) == "stub"
    assert isinstance(get_embedding_provider(cfg), StubEmbeddingProvider)


def test_list_embedding_provider_names() -> None:
    assert list_embedding_provider_names() == ["stub", "openai", "local"]


def test_resolve_provider_name_local() -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="local")
    assert resolve_embedding_provider_name(cfg) == "local"
    assert isinstance(get_embedding_provider(cfg), LocalFastEmbedProvider)


def test_build_embedding_status_stub(monkeypatch) -> None:
    clear_embedding_provider_cache()
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_embedding_model="stub", llm_embedding_provider=""),
    )
    from pallas.product.llm.knowledge.embedding_provider import build_embedding_status

    status = build_embedding_status(probe=False)
    assert status["embedding_provider"] == "stub"
    assert status["semantic_available"] is False
    assert "local" in status["available_providers"]
    assert status["probe_ok"] is None


def test_capability_trace_includes_provider() -> None:
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="")
    trace = embedding_capability_trace(cfg)
    assert trace["embedding_provider"] == "stub"
    assert trace["semantic_available"] is False


def test_openai_provider_with_stub_model_uses_default_and_needs_endpoint(monkeypatch) -> None:
    clear_embedding_provider_cache()
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_for_task",
        lambda *_a, **_k: type("E", (), {"base_url": "", "api_key": ""})(),
    )
    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="openai", llm_base_url="")
    assert resolve_remote_embedding_model(cfg) == "text-embedding-3-small"
    assert isinstance(get_embedding_provider(cfg), OpenAICompatibleEmbeddingProvider)
    trace = embedding_capability_trace(cfg)
    assert trace["embedding_provider"] == "openai"
    assert trace["semantic_available"] is False
    assert "地址" in str(trace["embedding_error"] or "")

    cfg2 = LlmConfig(
        llm_embedding_model="stub",
        llm_embedding_provider="openai",
        llm_base_url="https://example.test/v1",
        llm_api_key="k",
    )
    trace2 = embedding_capability_trace(cfg2)
    assert trace2["semantic_available"] is True
    assert trace2["resolved_model"] == "text-embedding-3-small"


def test_fetch_via_provider_openai(monkeypatch) -> None:
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
            return {"data": [{"index": 0, "embedding": [0.5, 0.5]}]}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_for_task",
        lambda *_a, **_k: type("E", (), {"base_url": "", "api_key": ""})(),
    )
    assert fetch_embeddings_sync(["hello"], cfg=cfg) == [[0.5, 0.5]]
    assert embedding_capability_trace(cfg)["embedding_provider"] == "openai"
