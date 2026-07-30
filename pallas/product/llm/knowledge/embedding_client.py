"""知识与记忆检索的 embedding 客户端（对外入口，内部走 EmbeddingProvider）。"""

from __future__ import annotations

import hashlib
from operator import itemgetter
from typing import TYPE_CHECKING, Any

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

if TYPE_CHECKING:
    from pallas.product.llm.config import LlmConfig

_DEFAULT_DIMS = 16
_last_embedding_error = ""


def embedding_model_name(cfg: LlmConfig | None = None) -> str:
    configured = str(getattr(cfg, "llm_embedding_model", "") or "").strip()
    if configured:
        return configured
    raw = repo_env_raw_value("LLM_EMBEDDING_MODEL")
    model = str(raw or "stub").strip()
    return model or "stub"


def embedding_capability_trace(cfg: LlmConfig | None = None) -> dict[str, Any]:
    from pallas.product.llm.knowledge.embedding_provider import (
        embedding_remote_endpoint_configured,
        local_embedding_dependency_available,
        resolve_embedding_provider_name,
        resolve_local_embedding_model,
        resolve_remote_embedding_model,
    )

    model = embedding_model_name(cfg)
    provider_name = resolve_embedding_provider_name(cfg)
    error = _last_embedding_error
    resolved_model = model
    if provider_name == "local":
        resolved_model = resolve_local_embedding_model(cfg)
        if not local_embedding_dependency_available():
            error = error or "未安装 fastembed；请执行 uv sync --extra embedding-local"
            semantic = False
        else:
            semantic = not bool(_last_embedding_error)
    elif provider_name == "openai":
        resolved_model = resolve_remote_embedding_model(cfg)
        if not embedding_remote_endpoint_configured(cfg):
            error = error or (
                "未配置向量服务地址：请填写「Embedding 接口地址」，或先在对话 Provider 配好可用的 OpenAI 兼容地址"
            )
            semantic = False
        elif model.lower() == "stub":
            # 选了 openai 但模型仍写 stub 时，运行会用默认远程模型名
            semantic = not bool(_last_embedding_error)
        else:
            semantic = not bool(_last_embedding_error)
    else:
        semantic = False
    return {
        "embedding_provider": provider_name,
        "embedding_model": model,
        "resolved_model": resolved_model,
        "embedding_fallback": bool(error),
        "embedding_error": error or None,
        "semantic_available": semantic,
    }


def stub_embedding(text: str, *, dims: int = _DEFAULT_DIMS) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    out: list[float] = []
    for i in range(dims):
        byte = digest[i % len(digest)]
        out.append((byte / 255.0) * 2.0 - 1.0)
    return out


def parse_embeddings_response(payload: object) -> list[list[float]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    parsed: list[tuple[int, list[float]]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        vec = item.get("embedding")
        if not isinstance(vec, list) or not vec:
            continue
        try:
            floats = [float(x) for x in vec]
        except (TypeError, ValueError):
            continue
        raw_index = item.get("index")
        index = int(raw_index) if raw_index is not None else len(parsed)
        parsed.append((index, floats))
    parsed.sort(key=itemgetter(0))
    return [vec for _, vec in parsed]


def fetch_embeddings_sync(
    texts: list[str],
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 8.0,
) -> list[list[float]] | None:
    global _last_embedding_error  # noqa: PLW0603
    inputs = [str(text or "").strip() for text in texts]
    if not inputs or any(not text for text in inputs):
        return None
    from pallas.product.llm.knowledge.embedding_provider import get_embedding_provider

    provider = get_embedding_provider(cfg)
    try:
        vectors = provider.embed_sync(inputs, timeout_sec=timeout_sec)
        if len(vectors) != len(inputs):
            raise ValueError("embedding response count mismatch")
        _last_embedding_error = ""
        return vectors
    except Exception as exc:
        _last_embedding_error = str(exc)[:240]
        # 远程失败回落 stub，保证调用方不中断
        return [stub_embedding(text) for text in inputs]


def embeddings_payload_for_api(texts: list[str], *, model: str | None = None) -> dict[str, Any]:
    """兼容旧 OpenAI embeddings 响应形状（测试/调试用）。"""
    inputs = [str(text or "") for text in texts]
    name = (model or embedding_model_name()).strip() or "stub"
    data = [{"object": "embedding", "index": idx, "embedding": stub_embedding(text)} for idx, text in enumerate(inputs)]
    return {
        "object": "list",
        "model": name,
        "data": data,
        "usage": {
            "prompt_tokens": sum(len(text) for text in inputs),
            "total_tokens": sum(len(text) for text in inputs),
        },
    }
