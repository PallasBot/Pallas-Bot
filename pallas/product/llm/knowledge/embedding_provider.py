"""Embedding Provider：可插拔向量后端（stub / OpenAI 兼容；本地预留）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

import httpx

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.product.llm.knowledge.embedding_client import (
    embedding_model_name,
    parse_embeddings_response,
    stub_embedding,
)

if TYPE_CHECKING:
    from pallas.product.llm.config import LlmConfig

EmbeddingProviderKind = Literal["stub", "remote", "local"]

_provider_cache: dict[str, EmbeddingProvider] = {}


class EmbeddingProvider(Protocol):
    """向量提供方协议。"""

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> EmbeddingProviderKind: ...

    def model_name(self) -> str: ...

    def embed_sync(self, texts: list[str], *, timeout_sec: float = 8.0) -> list[list[float]]: ...


@dataclass(frozen=True)
class StubEmbeddingProvider:
    dims: int = 16

    @property
    def name(self) -> str:
        return "stub"

    @property
    def kind(self) -> EmbeddingProviderKind:
        return "stub"

    def model_name(self) -> str:
        return "stub"

    def embed_sync(self, texts: list[str], *, timeout_sec: float = 8.0) -> list[list[float]]:
        del timeout_sec
        return [stub_embedding(text, dims=self.dims) for text in texts]


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingProvider:
    """OpenAI 兼容 /embeddings；默认复用聊天端点凭据，模型名来自配置。"""

    cfg: LlmConfig | None = None

    @property
    def name(self) -> str:
        return "openai"

    @property
    def kind(self) -> EmbeddingProviderKind:
        return "remote"

    def model_name(self) -> str:
        return embedding_model_name(self.cfg)

    def embed_sync(self, texts: list[str], *, timeout_sec: float = 8.0) -> list[list[float]]:
        from pallas.product.llm.provider_client import auth_headers, openai_api_root
        from pallas.product.llm.providers_store import resolve_endpoint_for_task

        model = self.model_name()
        endpoint = resolve_endpoint_for_task("llm_chat")
        base_url = str(getattr(endpoint, "base_url", "") or getattr(self.cfg, "llm_base_url", "") or "").strip()
        api_key = str(getattr(endpoint, "api_key", "") or getattr(self.cfg, "llm_api_key", "") or "").strip()
        # 可选独立 embedding 端点（未配则沿用聊天端点）
        override_base = str(repo_env_raw_value("LLM_EMBEDDING_BASE_URL") or "").strip()
        override_key = str(repo_env_raw_value("LLM_EMBEDDING_API_KEY") or "").strip()
        if override_base:
            base_url = override_base
        if override_key:
            api_key = override_key
        if not base_url:
            raise ValueError("embedding provider base_url not configured")
        response = httpx.post(
            f"{openai_api_root(base_url)}/embeddings",
            headers=auth_headers(api_key),
            json={"model": model, "input": texts},
            timeout=timeout_sec,
        )
        response.raise_for_status()
        vectors = parse_embeddings_response(response.json())
        if len(vectors) != len(texts):
            raise ValueError("embedding response count mismatch")
        return vectors


def resolve_embedding_provider_name(cfg: LlmConfig | None = None) -> str:
    configured = str(getattr(cfg, "llm_embedding_provider", "") or "").strip().lower()
    if configured in {"stub", "openai", "openai_compatible"}:
        return "stub" if configured == "stub" else "openai"
    raw = str(repo_env_raw_value("LLM_EMBEDDING_PROVIDER") or "").strip().lower()
    if raw in {"stub", "openai", "openai_compatible"}:
        return "stub" if raw == "stub" else "openai"
    model = embedding_model_name(cfg)
    if model.lower() == "stub":
        return "stub"
    return "openai"


def clear_embedding_provider_cache() -> None:
    _provider_cache.clear()


def get_embedding_provider(cfg: LlmConfig | None = None) -> EmbeddingProvider:
    name = resolve_embedding_provider_name(cfg)
    model = embedding_model_name(cfg)
    cache_key = f"{name}|{model}"
    hit = _provider_cache.get(cache_key)
    if hit is not None:
        return hit
    if name == "stub":
        provider: EmbeddingProvider = StubEmbeddingProvider()
    else:
        provider = OpenAICompatibleEmbeddingProvider(cfg=cfg)
    _provider_cache[cache_key] = provider
    return provider


def list_embedding_provider_names() -> list[str]:
    """已实现提供方；local 预留注册位，本版未内置。"""
    return ["stub", "openai"]
