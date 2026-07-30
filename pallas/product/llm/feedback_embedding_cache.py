"""Feedback 语义匹配用的 embedding 缓存：trigger 落盘预热 + query 进程内短 TTL。"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from nonebot import logger

from pallas.product.llm.knowledge.embedding_client import embedding_model_name, fetch_embeddings_sync

if TYPE_CHECKING:
    from pathlib import Path

_QUERY_CACHE_TTL_SEC = 20.0
_QUERY_CACHE_MAX = 512
_TRIGGER_CACHE_MAX = 4000
_LOCK = threading.RLock()
_query_cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
_trigger_mem: dict[str, list[float]] = {}
_trigger_model = ""
_trigger_loaded_path = ""
_prefetch_inflight: set[str] = set()
_backfill_started = False


def _text_key(text: str) -> str:
    return hashlib.sha256(str(text or "").strip().encode("utf-8")).hexdigest()


def _query_cache_key(model: str, text: str) -> str:
    return f"{model}|{_text_key(text)}"


def trigger_embeddings_path() -> Path:
    from pallas.product.llm.repeater_feedback import feedback_base_dir

    return feedback_base_dir() / "trigger_embeddings.json"


def clear_feedback_embedding_caches_for_tests() -> None:
    global _trigger_model, _trigger_loaded_path, _backfill_started
    with _LOCK:
        _query_cache.clear()
        _trigger_mem.clear()
        _trigger_model = ""
        _trigger_loaded_path = ""
        _prefetch_inflight.clear()
        _backfill_started = False


def invalidate_feedback_embedding_caches() -> None:
    """配置/模型变更后丢掉内存缓存，下次按新模型重新加载或回填。"""
    global _trigger_model, _trigger_loaded_path
    with _LOCK:
        _query_cache.clear()
        _trigger_mem.clear()
        _trigger_model = ""
        _trigger_loaded_path = ""
        _prefetch_inflight.clear()


def _load_trigger_file(path: Path, model: str) -> None:
    global _trigger_model, _trigger_loaded_path
    _trigger_mem.clear()
    _trigger_model = model
    _trigger_loaded_path = str(path)
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("feedback trigger embedding load failed: {}", exc)
        return
    if not isinstance(payload, dict):
        return
    if str(payload.get("model") or "") != model:
        return
    items = payload.get("items")
    if not isinstance(items, dict):
        return
    for key, row in items.items():
        if not isinstance(row, dict):
            continue
        vec = row.get("vec")
        if not isinstance(vec, list) or not vec:
            continue
        try:
            floats = [float(x) for x in vec]
        except (TypeError, ValueError):
            continue
        _trigger_mem[str(key)] = floats


def ensure_trigger_cache_loaded() -> str:
    model = embedding_model_name()
    path = trigger_embeddings_path()
    path_key = str(path)
    with _LOCK:
        if _trigger_loaded_path == path_key and _trigger_model == model:
            return model
        _load_trigger_file(path, model)
        return model


def _persist_trigger_file(path: Path, model: str) -> None:
    items: dict[str, Any] = {}
    # 保留最近写入的条目，避免文件无限涨
    keys = list(_trigger_mem.keys())
    if len(keys) > _TRIGGER_CACHE_MAX:
        keys = keys[-_TRIGGER_CACHE_MAX:]
        trimmed = {k: _trigger_mem[k] for k in keys}
        _trigger_mem.clear()
        _trigger_mem.update(trimmed)
    for key, vec in _trigger_mem.items():
        items[key] = {"vec": vec}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"model": model, "items": items}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(path)


def get_cached_trigger_embedding(text: str) -> list[float] | None:
    plain = str(text or "").strip()
    if not plain:
        return None
    ensure_trigger_cache_loaded()
    with _LOCK:
        vec = _trigger_mem.get(_text_key(plain))
        return list(vec) if vec is not None else None


def get_cached_query_embedding(text: str) -> list[float] | None:
    plain = str(text or "").strip()
    if not plain:
        return None
    model = embedding_model_name()
    key = _query_cache_key(model, plain)
    now = time.monotonic()
    with _LOCK:
        hit = _query_cache.get(key)
        if hit is None:
            return None
        expire_at, vec = hit
        if now >= expire_at:
            _query_cache.pop(key, None)
            return None
        _query_cache.move_to_end(key)
        return list(vec)


def store_query_embedding(text: str, vec: list[float]) -> None:
    plain = str(text or "").strip()
    if not plain or not vec:
        return
    model = embedding_model_name()
    key = _query_cache_key(model, plain)
    with _LOCK:
        _query_cache[key] = (time.monotonic() + _QUERY_CACHE_TTL_SEC, list(vec))
        _query_cache.move_to_end(key)
        while len(_query_cache) > _QUERY_CACHE_MAX:
            _query_cache.popitem(last=False)


def store_trigger_embeddings(pairs: list[tuple[str, list[float]]]) -> None:
    if not pairs:
        return
    model = ensure_trigger_cache_loaded()
    path = trigger_embeddings_path()
    with _LOCK:
        for text, vec in pairs:
            plain = str(text or "").strip()
            if not plain or not vec:
                continue
            _trigger_mem[_text_key(plain)] = list(vec)
        try:
            _persist_trigger_file(path, model)
        except OSError as exc:
            logger.debug("feedback trigger embedding persist failed: {}", exc)


def resolve_query_embedding(
    text: str,
    *,
    allow_remote: bool,
    timeout_sec: float = 8.0,
) -> list[float] | None:
    cached = get_cached_query_embedding(text)
    if cached is not None:
        return cached
    if not allow_remote:
        return None
    plain = str(text or "").strip()
    if not plain:
        return None
    vectors = fetch_embeddings_sync([plain], timeout_sec=timeout_sec)
    if not vectors or len(vectors) != 1:
        return None
    store_query_embedding(plain, vectors[0])
    return list(vectors[0])


def ensure_trigger_embeddings(
    texts: list[str],
    *,
    allow_remote: bool,
    timeout_sec: float = 8.0,
) -> dict[str, list[float]]:
    """返回 text -> vec；缺失且允许远程时批量补齐并落盘。"""
    ensure_trigger_cache_loaded()
    out: dict[str, list[float]] = {}
    missing: list[str] = []
    seen_miss: set[str] = set()
    for raw in texts:
        plain = str(raw or "").strip()
        if not plain:
            continue
        cached = get_cached_trigger_embedding(plain)
        if cached is not None:
            out[plain] = cached
            continue
        if plain not in seen_miss:
            seen_miss.add(plain)
            missing.append(plain)
    if not missing or not allow_remote:
        return out
    vectors = fetch_embeddings_sync(missing, timeout_sec=timeout_sec)
    if not vectors or len(vectors) != len(missing):
        return out
    pairs = list(zip(missing, vectors, strict=True))
    store_trigger_embeddings(pairs)
    for text, vec in pairs:
        out[text] = list(vec)
    return out


def prefetch_trigger_embedding(text: str) -> None:
    """append 后后台预热；失败忽略。"""
    plain = str(text or "").strip()
    if not plain:
        return
    if get_cached_trigger_embedding(plain) is not None:
        return
    key = _text_key(plain)
    with _LOCK:
        if key in _prefetch_inflight:
            return
        _prefetch_inflight.add(key)

    def _run() -> None:
        try:
            ensure_trigger_embeddings([plain], allow_remote=True, timeout_sec=8.0)
        except Exception as exc:
            logger.debug("feedback trigger embedding prefetch failed: {}", exc)
        finally:
            with _LOCK:
                _prefetch_inflight.discard(key)

    threading.Thread(target=_run, name="feedback-trigger-embed", daemon=True).start()


def collect_recent_feedback_trigger_texts(*, limit: int = 200) -> list[str]:
    """从 feedback 落盘条目收集近期去重 trigger 文本（新→旧）。"""
    from pallas.product.llm.repeater_feedback import _iter_feedback_entries, feedback_entries_path

    path = feedback_entries_path()
    if not path.exists():
        return []
    lim = max(1, int(limit))
    seen: set[str] = set()
    ordered: list[str] = []
    # 文件大致按追加顺序；先扫全量再取尾部，避免只看到最旧条目
    all_texts: list[str] = []
    for item in _iter_feedback_entries(path):
        plain = str(item.user_text or "").strip()
        if plain:
            all_texts.append(plain)
    for plain in reversed(all_texts):
        if plain in seen:
            continue
        seen.add(plain)
        ordered.append(plain)
        if len(ordered) >= lim:
            break
    ordered.reverse()
    return ordered


def backfill_feedback_trigger_embeddings(
    *,
    limit_texts: int = 200,
    batch_size: int = 32,
    timeout_sec: float = 8.0,
) -> dict[str, int]:
    """补齐近期缺失的 trigger 向量；供启动后台或运维调用。"""
    from pallas.product.llm.knowledge.embedding_provider import resolve_embedding_provider_name

    if resolve_embedding_provider_name() == "stub":
        return {"scanned": 0, "missing": 0, "filled": 0, "skipped_stub": 1}
    texts = collect_recent_feedback_trigger_texts(limit=limit_texts)
    missing = [t for t in texts if get_cached_trigger_embedding(t) is None]
    filled = 0
    batch = max(1, int(batch_size))
    for i in range(0, len(missing), batch):
        chunk = missing[i : i + batch]
        before = {t: get_cached_trigger_embedding(t) is not None for t in chunk}
        ensure_trigger_embeddings(chunk, allow_remote=True, timeout_sec=timeout_sec)
        for t in chunk:
            if not before.get(t) and get_cached_trigger_embedding(t) is not None:
                filled += 1
    return {
        "scanned": len(texts),
        "missing": len(missing),
        "filled": filled,
        "skipped_stub": 0,
    }


def schedule_feedback_trigger_backfill(*, limit_texts: int = 120, batch_size: int = 24) -> None:
    """进程内只排一次的后台回填，避免拖启动。"""
    global _backfill_started
    with _LOCK:
        if _backfill_started:
            return
        _backfill_started = True

    def _run() -> None:
        try:
            stats = backfill_feedback_trigger_embeddings(
                limit_texts=limit_texts,
                batch_size=batch_size,
                timeout_sec=8.0,
            )
            if int(stats.get("filled") or 0) > 0 or int(stats.get("missing") or 0) > 0:
                logger.info(
                    "feedback trigger embedding backfill scanned={} missing={} filled={}",
                    stats.get("scanned"),
                    stats.get("missing"),
                    stats.get("filled"),
                )
        except Exception as exc:
            logger.debug("feedback trigger embedding backfill failed: {}", exc)

    threading.Thread(target=_run, name="feedback-trigger-backfill", daemon=True).start()
