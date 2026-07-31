"""跨进程 Embedding：Redis 向量缓存 + 任务队列（复用 REDIS_URL / coord）。"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Literal

from nonebot import logger

from pallas.core.platform.shard.coord.coord_redis_store import redis_client_or_none

_PREFIX = "pallas:embed:v1"
JOBS_KEY = f"{_PREFIX}:jobs"
_QUERY_TTL_SEC = 180
_TRIGGER_TTL_SEC = 7 * 24 * 3600
_REPLY_TTL_SEC = 30


def _safe_model(model: str) -> str:
    return "".join(c if c.isalnum() or c in "-_./" else "_" for c in str(model or "").strip()) or "unknown"


def _text_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").strip().encode("utf-8")).hexdigest()


def embed_vec_key(model: str, text: str) -> str:
    return f"{_PREFIX}:vec:{_safe_model(model)}:{_text_hash(text)}"


def _reply_key(request_id: str) -> str:
    return f"{_PREFIX}:reply:{request_id}"


def redis_embed_available() -> bool:
    return redis_client_or_none() is not None


def get_cached_vec(model: str, text: str) -> list[float] | None:
    client = redis_client_or_none()
    if client is None:
        return None
    plain = str(text or "").strip()
    if not plain:
        return None
    try:
        raw = client.get(embed_vec_key(model, plain))
    except Exception as exc:
        logger.debug("embed redis get failed: {}", exc)
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, list) or not data:
        return None
    try:
        return [float(x) for x in data]
    except (TypeError, ValueError):
        return None


def set_cached_vec(
    model: str,
    text: str,
    vec: list[float],
    *,
    kind: Literal["query", "trigger"] = "query",
) -> bool:
    client = redis_client_or_none()
    if client is None or not vec:
        return False
    plain = str(text or "").strip()
    if not plain:
        return False
    ttl = _QUERY_TTL_SEC if kind == "query" else _TRIGGER_TTL_SEC
    try:
        client.setex(embed_vec_key(model, plain), int(ttl), json.dumps([float(x) for x in vec]))
        return True
    except Exception as exc:
        logger.debug("embed redis set failed: {}", exc)
        return False


def complete_embed_job(job: dict[str, Any], vectors: list[list[float]]) -> None:
    """worker 写回：缓存每条向量 + reply。"""
    model = str(job.get("model") or "").strip()
    texts = [str(t or "").strip() for t in (job.get("texts") or [])]
    request_id = str(job.get("request_id") or "").strip()
    kind_raw = str(job.get("kind") or "query").strip().lower()
    kind: Literal["query", "trigger"] = "trigger" if kind_raw == "trigger" else "query"
    if model and texts and len(vectors) == len(texts):
        for text, vec in zip(texts, vectors, strict=True):
            set_cached_vec(model, text, vec, kind=kind)
    client = redis_client_or_none()
    if client is None or not request_id:
        return
    try:
        client.setex(_reply_key(request_id), _REPLY_TTL_SEC, json.dumps(vectors))
    except Exception as exc:
        logger.debug("embed redis reply set failed: {}", exc)


def pop_embed_job(*, timeout_sec: float = 5.0) -> dict[str, Any] | None:
    client = redis_client_or_none()
    if client is None:
        return None
    try:
        item = client.brpop(JOBS_KEY, timeout=max(1, int(timeout_sec)))
    except Exception as exc:
        logger.debug("embed redis brpop failed: {}", exc)
        return None
    if not item:
        return None
    _key, raw = item
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def request_embeddings(
    texts: list[str],
    *,
    model: str,
    timeout_sec: float = 0.35,
    kind: Literal["query", "trigger"] = "query",
) -> list[list[float]] | None:
    """先读缓存；未命中则入队并短等 reply。全部命中则不入队。"""
    inputs = [str(t or "").strip() for t in texts]
    if not inputs or any(not t for t in inputs):
        return None
    model_name = str(model or "").strip()
    if not model_name:
        return None

    out: list[list[float] | None] = [None] * len(inputs)
    missing_idx: list[int] = []
    for i, text in enumerate(inputs):
        hit = get_cached_vec(model_name, text)
        if hit is not None:
            out[i] = hit
        else:
            missing_idx.append(i)
    if not missing_idx:
        return [list(v) for v in out]  # type: ignore[misc]

    client = redis_client_or_none()
    if client is None:
        return None

    miss_texts = [inputs[i] for i in missing_idx]
    request_id = uuid.uuid4().hex
    job = {
        "request_id": request_id,
        "model": model_name,
        "texts": miss_texts,
        "kind": kind,
    }
    try:
        client.lpush(JOBS_KEY, json.dumps(job, ensure_ascii=False))
    except Exception as exc:
        logger.debug("embed redis enqueue failed: {}", exc)
        return None

    deadline = time.monotonic() + max(0.05, float(timeout_sec))
    reply: list[list[float]] | None = None
    while time.monotonic() < deadline:
        try:
            raw = client.get(_reply_key(request_id))
        except Exception:
            raw = None
        if raw is not None:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                data = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                data = None
            if isinstance(data, list) and len(data) == len(miss_texts):
                try:
                    reply = [[float(x) for x in row] for row in data]
                except (TypeError, ValueError):
                    reply = None
                break
        time.sleep(0.01)
    if reply is None:
        return None
    for i, vec in zip(missing_idx, reply, strict=True):
        out[i] = vec
    if any(v is None for v in out):
        return None
    return [list(v) for v in out]  # type: ignore[misc]
