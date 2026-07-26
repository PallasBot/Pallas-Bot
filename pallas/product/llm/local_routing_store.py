"""Bot 侧 Ollama 分档 / 本地默认模型配置（原 AI local-routing）。"""

from __future__ import annotations

import json
import threading
from pathlib import Path  # noqa: TC003
from typing import Any

from nonebot import logger

from pallas.core.foundation.paths import DATA_ROOT

_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None
LOCAL_ROUTING_FILENAME = "llm_local_routing.json"

_EMPTY_MOE = {"simple": "", "medium": "", "complex": "", "vision": ""}
_EMPTY_TASKS = {
    "llm_chat": "",
    "drunk": "",
    "repeater_fallback": "",
    "repeater_polish": "",
    "repeater_polish_lite": "",
    "repeater_select": "",
    "affect_refine": "",
}


def local_routing_store_path() -> Path:
    return DATA_ROOT / "pallas_config" / LOCAL_ROUTING_FILENAME


def clear_local_routing_cache() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = None


def _empty_document() -> dict[str, Any]:
    return {
        "llm_model": "",
        "local_multi_model_enabled": False,
        "moe_models": dict(_EMPTY_MOE),
        "task_models": dict(_EMPTY_TASKS),
    }


def _normalize_str_map(raw: Any, allowed: dict[str, str]) -> dict[str, str]:
    out = dict(allowed)
    if not isinstance(raw, dict):
        return out
    for key in allowed:
        out[key] = str(raw.get(key) or "").strip()
    return out


def _normalize_document(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    return {
        "llm_model": str(src.get("llm_model") or "").strip(),
        "local_multi_model_enabled": bool(src.get("local_multi_model_enabled")),
        "moe_models": _normalize_str_map(src.get("moe_models"), _EMPTY_MOE),
        "task_models": _normalize_str_map(src.get("task_models"), _EMPTY_TASKS),
    }


def load_local_routing_document() -> dict[str, Any]:
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return dict(_CACHE)
        path = local_routing_store_path()
        if not path.is_file():
            _CACHE = _empty_document()
            return dict(_CACHE)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("load local routing failed: path={}", path)
            _CACHE = _empty_document()
            return dict(_CACHE)
        _CACHE = _normalize_document(payload if isinstance(payload, dict) else {})
        return dict(_CACHE)


def save_local_routing_document(raw: dict[str, Any]) -> dict[str, Any]:
    global _CACHE
    doc = _normalize_document(raw)
    path = local_routing_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        _CACHE = dict(doc)
    logger.info("llm local routing saved: path={}", path)
    return export_local_routing_for_api(doc=doc)


def export_local_routing_for_api(*, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _normalize_document(doc if isinstance(doc, dict) else load_local_routing_document())
    path = local_routing_store_path()
    return {
        **payload,
        "env_file": str(path),
    }


def resolve_local_task_model(task: str) -> str:
    """多模型开启时按任务键取分档模型名。"""
    doc = load_local_routing_document()
    if not doc.get("local_multi_model_enabled"):
        return str(doc.get("llm_model") or "").strip()
    key = str(task or "").strip().lower()
    tasks = doc.get("task_models") if isinstance(doc.get("task_models"), dict) else {}
    model = str(tasks.get(key) or "").strip()
    if model:
        return model
    return str(doc.get("llm_model") or "").strip()
