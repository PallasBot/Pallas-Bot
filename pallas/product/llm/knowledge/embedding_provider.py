"""Embedding Provider：可插拔向量后端（stub / OpenAI 兼容 / 可选本地）。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

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

_DEFAULT_LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"
_DEFAULT_REMOTE_MODEL = "text-embedding-3-small"
_provider_cache: dict[str, EmbeddingProvider] = {}
_local_model_lock = threading.Lock()
_local_models: dict[str, Any] = {}


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
        return resolve_remote_embedding_model(self.cfg)

    def embed_sync(self, texts: list[str], *, timeout_sec: float = 8.0) -> list[list[float]]:
        from pallas.product.llm.provider_client import auth_headers, openai_api_root
        from pallas.product.llm.providers_store import resolve_endpoint_for_task

        model = self.model_name()
        endpoint = resolve_endpoint_for_task("llm_chat")
        base_url = str(getattr(endpoint, "base_url", "") or getattr(self.cfg, "llm_base_url", "") or "").strip()
        api_key = str(getattr(endpoint, "api_key", "") or getattr(self.cfg, "llm_api_key", "") or "").strip()
        # 可选独立 embedding 端点（未配则沿用聊天端点）
        override_base = str(
            getattr(self.cfg, "llm_embedding_base_url", "") or repo_env_raw_value("LLM_EMBEDDING_BASE_URL") or ""
        ).strip()
        override_key = str(
            getattr(self.cfg, "llm_embedding_api_key", "") or repo_env_raw_value("LLM_EMBEDDING_API_KEY") or ""
        ).strip()
        if override_base:
            base_url = override_base
        if override_key:
            api_key = override_key
        if not base_url:
            raise ValueError(
                "embedding provider base_url not configured（请填 Embedding 接口地址，或配置对话 Provider）"
            )
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


def local_embedding_dependency_available() -> bool:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


def resolve_local_embedding_model(cfg: LlmConfig | None = None) -> str:
    model = embedding_model_name(cfg).strip()
    if not model or model.lower() == "stub":
        return _DEFAULT_LOCAL_MODEL
    return model


def resolve_remote_embedding_model(cfg: LlmConfig | None = None) -> str:
    """openai 提供方：模型仍写 stub 时落到默认远程模型名。"""
    model = embedding_model_name(cfg).strip()
    if not model or model.lower() == "stub":
        return _DEFAULT_REMOTE_MODEL
    return model


def embedding_remote_endpoint_configured(cfg: LlmConfig | None = None) -> bool:
    override = str(
        getattr(cfg, "llm_embedding_base_url", "") or repo_env_raw_value("LLM_EMBEDDING_BASE_URL") or ""
    ).strip()
    if override:
        return True
    if str(getattr(cfg, "llm_base_url", "") or "").strip():
        return True
    try:
        from pallas.product.llm.providers_store import resolve_endpoint_for_task

        endpoint = resolve_endpoint_for_task("llm_chat")
        if str(getattr(endpoint, "base_url", "") or "").strip():
            return True
    except Exception:
        pass
    return False


def _load_local_fastembed_model(model_name: str) -> Any:
    with _local_model_lock:
        hit = _local_models.get(model_name)
        if hit is not None:
            return hit
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ImportError("本地 Embedding 需要 fastembed；请执行: uv sync --extra embedding-local") from exc
        model = TextEmbedding(model_name=model_name)
        _local_models[model_name] = model
        return model


@dataclass(frozen=True)
class LocalFastEmbedProvider:
    """本机 fastembed；首次加载可能较慢，应在后台线程调用。"""

    cfg: LlmConfig | None = None

    @property
    def name(self) -> str:
        return "local"

    @property
    def kind(self) -> EmbeddingProviderKind:
        return "local"

    def model_name(self) -> str:
        return resolve_local_embedding_model(self.cfg)

    def embed_sync(self, texts: list[str], *, timeout_sec: float = 8.0) -> list[list[float]]:
        del timeout_sec
        model = _load_local_fastembed_model(self.model_name())
        vectors = [list(map(float, vec)) for vec in model.embed(texts)]
        if len(vectors) != len(texts):
            raise ValueError("local embedding response count mismatch")
        return vectors


def normalize_embedding_provider_name(raw: str) -> str:
    name = str(raw or "").strip().lower()
    if name in {"", "auto"}:
        return ""
    if name == "stub":
        return "stub"
    if name in {"openai", "openai_compatible"}:
        return "openai"
    if name in {"local", "fastembed"}:
        return "local"
    return ""


def resolve_embedding_provider_name(cfg: LlmConfig | None = None) -> str:
    configured = normalize_embedding_provider_name(str(getattr(cfg, "llm_embedding_provider", "") or ""))
    if configured:
        return configured
    raw = normalize_embedding_provider_name(str(repo_env_raw_value("LLM_EMBEDDING_PROVIDER") or ""))
    if raw:
        return raw
    model = embedding_model_name(cfg)
    if model.lower() == "stub":
        return "stub"
    return "openai"


def clear_embedding_provider_cache() -> None:
    _provider_cache.clear()


def clear_local_embedding_models_for_tests() -> None:
    with _local_model_lock:
        _local_models.clear()


def get_embedding_provider(cfg: LlmConfig | None = None) -> EmbeddingProvider:
    name = resolve_embedding_provider_name(cfg)
    if name == "local":
        model = resolve_local_embedding_model(cfg)
    elif name == "openai":
        model = resolve_remote_embedding_model(cfg)
    else:
        model = embedding_model_name(cfg)
    cache_key = f"{name}|{model}"
    hit = _provider_cache.get(cache_key)
    if hit is not None:
        return hit
    if name == "stub":
        provider: EmbeddingProvider = StubEmbeddingProvider()
    elif name == "local":
        provider = LocalFastEmbedProvider(cfg=cfg)
    else:
        provider = OpenAICompatibleEmbeddingProvider(cfg=cfg)
    _provider_cache[cache_key] = provider
    return provider


def list_embedding_provider_names() -> list[str]:
    return ["stub", "openai", "local"]


def build_embedding_status(*, probe: bool = False, probe_text: str = "ping") -> dict[str, Any]:
    """控制台诊断：当前提供方、是否语义可用、是否回落 stub。"""
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.knowledge.embedding_client import (
        embedding_capability_trace,
        fetch_embeddings_sync,
    )

    cfg = get_llm_config()
    provider = get_embedding_provider(cfg)
    trace = embedding_capability_trace(cfg)
    local_ready = local_embedding_dependency_available()
    if provider.name == "local" and not local_ready:
        trace = {
            **trace,
            "semantic_available": False,
            "embedding_fallback": True,
            "embedding_error": trace.get("embedding_error")
            or "未安装 fastembed；请执行 uv sync --extra embedding-local",
        }

    trigger_cached = 0
    trigger_model = ""
    try:
        from pallas.product.llm.feedback_embedding_cache import feedback_trigger_cache_stats

        stats = feedback_trigger_cache_stats()
        trigger_cached = int(stats.get("cached") or 0)
        trigger_model = str(stats.get("model") or "")
    except Exception:
        pass

    probe_ok: bool | None = None
    probe_dims: int | None = None
    probe_ms: float | None = None
    if probe:
        import time

        text = str(probe_text or "ping").strip() or "ping"
        started = time.perf_counter()
        vectors = fetch_embeddings_sync([text], cfg=cfg, timeout_sec=8.0)
        probe_ms = round((time.perf_counter() - started) * 1000.0, 1)
        probe_ok = bool(vectors and vectors[0])
        if vectors and vectors[0]:
            probe_dims = len(vectors[0])
        # 重新读 trace：fetch 可能写入 fallback 错误
        trace = embedding_capability_trace(cfg)

    return {
        **trace,
        "embedding_kind": provider.kind,
        "resolved_model": provider.model_name(),
        "available_providers": list_embedding_provider_names(),
        "local_dependency_ready": local_ready,
        "local_default_model": _DEFAULT_LOCAL_MODEL,
        "remote_default_model": _DEFAULT_REMOTE_MODEL,
        "endpoint_configured": embedding_remote_endpoint_configured(cfg),
        "trigger_cache_count": trigger_cached,
        "trigger_cache_model": trigger_model or None,
        "probe_ok": probe_ok,
        "probe_dims": probe_dims,
        "probe_ms": probe_ms,
    }
