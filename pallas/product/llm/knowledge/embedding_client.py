"""调用 AI 服务 `/api/v1/embeddings`（同步，供知识检索后端使用）。"""

from __future__ import annotations

from operator import itemgetter
from typing import Any

import httpx
from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.product.llm.config import LlmConfig, get_llm_config, llm_server_base_url


def embedding_model_name(cfg: LlmConfig | None = None) -> str:
    _ = cfg
    raw = repo_env_raw_value("LLM_EMBEDDING_MODEL")
    model = str(raw or "stub").strip()
    return model or "stub"


def embeddings_api_url(cfg: LlmConfig | None = None) -> str:
    c = cfg or get_llm_config()
    return f"{llm_server_base_url(c).rstrip('/')}/api/v1/embeddings"


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
    inputs = [str(text or "").strip() for text in texts]
    if not inputs or any(not text for text in inputs):
        return None
    url = embeddings_api_url(cfg)
    body: dict[str, Any] = {
        "input": inputs if len(inputs) > 1 else inputs[0],
        "model": embedding_model_name(cfg),
    }
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            response = client.post(url, json=body)
    except Exception as exc:
        logger.warning("knowledge embeddings request failed: {}", exc)
        return None
    if response is None or response.status_code >= 400:
        code = response.status_code if response is not None else "?"
        logger.warning("knowledge embeddings HTTP {} url={}", code, url)
        return None
    try:
        payload = response.json()
    except Exception:
        logger.warning("knowledge embeddings invalid json url={}", url)
        return None
    vectors = parse_embeddings_response(payload)
    if len(vectors) != len(inputs):
        logger.warning(
            "knowledge embeddings size mismatch expected={} got={}",
            len(inputs),
            len(vectors),
        )
        return None
    return vectors
