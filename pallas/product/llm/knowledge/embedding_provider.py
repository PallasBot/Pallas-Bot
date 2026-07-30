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


def resolve_embedding_catalog_provider_id(cfg: LlmConfig | None = None) -> str:
    """Embedding 线路选用的 LLM Provider 名册 id（可空=回落对话主线）。"""
    return str(
        getattr(cfg, "llm_embedding_provider_id", "") or repo_env_raw_value("LLM_EMBEDDING_PROVIDER_ID") or ""
    ).strip()


def resolve_embedding_http_endpoint(cfg: LlmConfig | None = None) -> tuple[str, str, str]:
    """解析 Embedding HTTP 端点：(base_url, api_key, source_provider_id)。

    优先级：手填 base/key → 名册 ``llm_embedding_provider_id`` → 对话主线 / ``llm_base_url``。
    """
    from pallas.product.llm.providers_store import (
        find_provider,
        resolve_endpoint_for_task,
        resolve_provider_api_key,
        resolve_provider_base_url,
    )

    override_base = str(
        getattr(cfg, "llm_embedding_base_url", "") or repo_env_raw_value("LLM_EMBEDDING_BASE_URL") or ""
    ).strip()
    override_key = str(
        getattr(cfg, "llm_embedding_api_key", "") or repo_env_raw_value("LLM_EMBEDDING_API_KEY") or ""
    ).strip()
    catalog_id = resolve_embedding_catalog_provider_id(cfg)

    base_url = ""
    api_key = ""
    source_id = ""

    if catalog_id:
        row = find_provider(catalog_id)
        if row is not None:
            base_url = resolve_provider_base_url(row)
            api_key = resolve_provider_api_key(row)
            source_id = catalog_id

    if not base_url or not api_key:
        endpoint = resolve_endpoint_for_task("llm_chat")
        chat_base = str(getattr(endpoint, "base_url", "") or getattr(cfg, "llm_base_url", "") or "").strip()
        chat_key = str(getattr(endpoint, "api_key", "") or getattr(cfg, "llm_api_key", "") or "").strip()
        chat_id = str(getattr(endpoint, "provider_id", "") or "").strip()
        if not base_url and chat_base:
            base_url = chat_base
            if not source_id:
                source_id = chat_id
        if not api_key and chat_key:
            api_key = chat_key

    if override_base:
        base_url = override_base
        if not source_id:
            source_id = "manual"
    if override_key:
        api_key = override_key

    return base_url, api_key, source_id


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingProvider:
    """OpenAI 兼容 /embeddings；优先 Embedding 线路名册，否则复用聊天端点。"""

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

        model = self.model_name()
        base_url, api_key, _source = resolve_embedding_http_endpoint(self.cfg)
        if not base_url:
            raise ValueError(
                "embedding provider base_url not configured（请在 Embedding 线路选 Provider，或填接口地址）"
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
    base_url, _api_key, _source = resolve_embedding_http_endpoint(cfg)
    return bool(base_url)


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

    catalog_id = resolve_embedding_catalog_provider_id(cfg)
    endpoint_source = ""
    if provider.name == "openai":
        _base, _key, endpoint_source = resolve_embedding_http_endpoint(cfg)

    return {
        **trace,
        "embedding_kind": provider.kind,
        "resolved_model": provider.model_name(),
        "embedding_provider_id": catalog_id or None,
        "endpoint_provider_id": endpoint_source or None,
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
