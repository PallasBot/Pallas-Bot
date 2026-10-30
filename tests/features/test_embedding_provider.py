from __future__ import annotations

import json
import sys

import httpx
import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.embedding_client import (
    embedding_capability_trace,
    fetch_embeddings_sync,
)
from pallas.product.llm.knowledge.embedding_provider import (
    OpenAICompatibleEmbeddingProvider,
    RedisQueueEmbeddingProvider,
    StubEmbeddingProvider,
    clear_embedding_provider_cache,
    get_embedding_provider,
    list_embedding_provider_names,
    resolve_embedding_provider_name,
    resolve_remote_embedding_model,
)


def _ignore_webui_embedding_env(monkeypatch) -> None:
    """单测用 cfg 字段，避免本机 webui.json 的 local 覆盖空 provider。"""
    import pallas.product.llm.knowledge.embedding_provider as ep

    real = ep.repo_env_raw_value

    def fake(key: str):
        if str(key).upper().startswith("LLM_EMBEDDING"):
            return None
        return real(key)

    monkeypatch.setattr(ep, "repo_env_raw_value", fake)


def test_resolve_provider_name_infers_stub_from_model(monkeypatch) -> None:
    _ignore_webui_embedding_env(monkeypatch)
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="")
    assert resolve_embedding_provider_name(cfg) == "stub"
    assert isinstance(get_embedding_provider(cfg), StubEmbeddingProvider)


def test_resolve_provider_name_openai_when_model_set(monkeypatch) -> None:
    _ignore_webui_embedding_env(monkeypatch)
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
    # 业务进程走 Redis 队列封装，不在进程内加载 fastembed
    assert isinstance(get_embedding_provider(cfg), RedisQueueEmbeddingProvider)


def test_build_embedding_status_stub(monkeypatch) -> None:
    _ignore_webui_embedding_env(monkeypatch)
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


def test_capability_trace_includes_provider(monkeypatch) -> None:
    _ignore_webui_embedding_env(monkeypatch)
    clear_embedding_provider_cache()
    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="")
    trace = embedding_capability_trace(cfg)
    assert trace["embedding_provider"] == "stub"
    assert trace["semantic_available"] is False


def test_openai_provider_with_stub_model_uses_default_and_needs_endpoint(monkeypatch) -> None:
    from pallas.product.llm.knowledge import embedding_client

    embedding_client._last_embedding_error = ""
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
        llm_chat_enabled=True,
    )

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.5, 0.5]}]}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_for_task",
        lambda *_a, **_k: type("E", (), {"base_url": "", "api_key": "", "provider_id": ""})(),
    )
    assert fetch_embeddings_sync(["hello"], cfg=cfg) == [[0.5, 0.5]]
    assert embedding_capability_trace(cfg)["embedding_provider"] == "openai"


def test_fetch_provider_cache_tracks_new_config_route_and_key(monkeypatch) -> None:
    import pallas.product.llm.knowledge.embedding_provider as ep

    clear_embedding_provider_cache()
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_for_task",
        lambda *_a, **_k: type("E", (), {"base_url": "", "api_key": "", "provider_id": ""})(),
    )
    calls: list[tuple[str, str, str]] = []

    def vendor(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append((request.url.host, request.headers.get("authorization", ""), payload["model"]))
        value = 1.0 if request.url.host == "embed-a.invalid" else 2.0
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [value, value + 1]}]})

    client = httpx.Client(transport=httpx.MockTransport(vendor), trust_env=False)
    monkeypatch.setattr(ep.httpx, "post", client.post)
    cfg_a = LlmConfig(
        llm_chat_enabled=True,
        llm_embedding_provider="openai",
        llm_embedding_model="shared-model",
        llm_embedding_base_url="https://embed-a.invalid/v1",
        llm_embedding_api_key="synthetic-key-a",
    )
    cfg_b = cfg_a.model_copy(
        update={
            "llm_embedding_base_url": "https://embed-b.invalid/v1",
            "llm_embedding_api_key": "synthetic-key-b",
        }
    )
    cfg_b_rotated = cfg_b.model_copy(update={"llm_embedding_api_key": "synthetic-key-c"})
    try:
        provider_a = get_embedding_provider(cfg_a)
        assert get_embedding_provider(cfg_a) is provider_a
        assert fetch_embeddings_sync(["same input"], cfg=cfg_a, fallback_stub=False) == [[1.0, 2.0]]

        provider_b = get_embedding_provider(cfg_b)
        assert provider_b is not provider_a
        assert provider_b.cfg is cfg_b
        assert fetch_embeddings_sync(["same input"], cfg=cfg_b, fallback_stub=False) == [[2.0, 3.0]]
        assert fetch_embeddings_sync(["same input"], cfg=cfg_b_rotated, fallback_stub=False) == [[2.0, 3.0]]
    finally:
        client.close()
        clear_embedding_provider_cache()

    assert calls == [
        ("embed-a.invalid", "Bearer synthetic-key-a", "shared-model"),
        ("embed-b.invalid", "Bearer synthetic-key-b", "shared-model"),
        ("embed-b.invalid", "Bearer synthetic-key-c", "shared-model"),
    ]


def test_resolve_embedding_http_endpoint_prefers_catalog(monkeypatch) -> None:
    from pallas.product.llm.knowledge.embedding_provider import resolve_embedding_http_endpoint

    monkeypatch.setattr(
        "pallas.product.llm.providers_store.find_provider",
        lambda pid, **_k: {
            "id": pid,
            "base_url": "https://embed.example/v1",
            "api_key": "embed-key",
            "api_keys": ["embed-key"],
        },
    )
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_for_task",
        lambda *_a, **_k: type(
            "E", (), {"base_url": "https://chat.example", "api_key": "chat-key", "provider_id": "ds"}
        )(),
    )
    cfg = LlmConfig(
        llm_embedding_provider="openai",
        llm_embedding_provider_id="packy",
        llm_embedding_model="text-embedding-3-small",
    )
    base, key, source = resolve_embedding_http_endpoint(cfg)
    assert base == "https://embed.example/v1"
    assert key == "embed-key"
    assert source == "packy"


def test_local_dependency_hint_uses_project_sync(monkeypatch) -> None:
    import pallas.product.llm.knowledge.embedding_provider as ep
    from pallas.product.llm.knowledge import embedding_client

    monkeypatch.setattr(embedding_client, "_last_embedding_error", "")
    monkeypatch.setattr(ep, "local_embedding_dependency_available", lambda: False)
    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="local")

    trace = embedding_capability_trace(cfg)

    assert "uv sync --inexact --extra embedding-local" in str(trace["embedding_error"])


def test_build_embedding_status_dependency_hint_uses_project_sync(monkeypatch) -> None:
    import pallas.product.llm.knowledge.embedding_provider as ep

    cfg = LlmConfig(llm_embedding_model="stub", llm_embedding_provider="local")
    monkeypatch.setattr(ep, "local_embedding_dependency_available", lambda: False)
    monkeypatch.setattr(
        "pallas.product.llm.knowledge.embedding_client.embedding_capability_trace",
        lambda _cfg=None: {"embedding_error": None},
    )
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.knowledge.embed_redis.redis_embed_available", lambda: True)

    status = ep.build_embedding_status(probe=False)

    assert "uv sync --inexact --extra embedding-local" in str(status["embedding_error"])


def test_local_model_import_error_hint_uses_project_sync(monkeypatch) -> None:
    import pallas.product.llm.knowledge.embedding_provider as ep

    monkeypatch.setattr(ep, "_local_models", {})
    monkeypatch.setitem(sys.modules, "fastembed", None)

    with pytest.raises(ImportError) as exc_info:
        ep._load_local_fastembed_model("BAAI/bge-small-zh-v1.5")

    assert "uv sync --inexact --extra embedding-local" in str(exc_info.value)
