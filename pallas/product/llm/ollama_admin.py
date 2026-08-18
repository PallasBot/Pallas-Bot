"""Bot 直连 Ollama：运行态模型 / 拉取 / 卸载 / num_gpu。"""

from __future__ import annotations

import json
import threading
from pathlib import Path  # noqa: TC003
from typing import Any

import httpx
from nonebot import logger

from pallas.core.foundation.paths import DATA_ROOT
from pallas.product.llm.provider_client import LlmProviderError, normalize_openai_base_url

_LOCK = threading.RLock()
_RUNTIME_FILENAME = "llm_ollama_runtime.json"


def ollama_runtime_path() -> Path:
    return DATA_ROOT / "pallas_config" / _RUNTIME_FILENAME


def ollama_base_from_url(base_url: str) -> str:
    base = normalize_openai_base_url(base_url)
    if not base:
        raise LlmProviderError("ollama base url not configured")
    return base.removesuffix("/v1").rstrip("/")


def _read_runtime() -> dict[str, Any]:
    path = ollama_runtime_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_runtime(data: dict[str, Any]) -> None:
    path = ollama_runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)


def get_runtime_model_name(*, fallback: str = "") -> str:
    with _LOCK:
        model = _read_runtime().get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return str(fallback or "").strip()


def get_runtime_num_gpu() -> int | None:
    with _LOCK:
        value = _read_runtime().get("num_gpu")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def set_runtime_model_name(model: str) -> str:
    name = str(model or "").strip()
    if not name:
        raise ValueError("模型名不能为空")
    with _LOCK:
        data = _read_runtime()
        data["model"] = name
        _write_runtime(data)
    return name


def set_runtime_num_gpu_value(num_gpu: int | None) -> int | None:
    with _LOCK:
        data = _read_runtime()
        if num_gpu is None:
            data.pop("num_gpu", None)
        else:
            data["num_gpu"] = int(num_gpu)
        _write_runtime(data)
    return num_gpu


async def ping_ollama(base_url: str, *, timeout_sec: float = 3.0) -> bool:
    root = ollama_base_from_url(base_url)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
            response = await client.get(f"{root}/api/tags")
        return response.status_code == 200
    except Exception:
        return False


async def pull_ollama_model(base_url: str, model: str, *, timeout_sec: float = 600.0) -> None:
    root = ollama_base_from_url(base_url)
    name = str(model or "").strip()
    if not name:
        return
    logger.info("Ollama pull started for model [{}]", name)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
        async with client.stream("POST", f"{root}/api/pull", json={"name": name}) as response:
            if response.status_code >= 400:
                raise LlmProviderError(f"HTTP {response.status_code}", status=response.status_code)
            async for _line in response.aiter_lines():
                pass
    logger.info("Ollama pull finished for model [{}]", name)


async def unload_ollama_model(base_url: str, model: str, *, timeout_sec: float = 60.0) -> None:
    root = ollama_base_from_url(base_url)
    name = str(model or "").strip()
    if not name:
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
        response = await client.post(
            f"{root}/api/generate",
            json={"model": name, "keep_alive": 0},
        )
    if response.status_code >= 400:
        raise LlmProviderError(f"HTTP {response.status_code}", status=response.status_code)
    logger.info("Ollama unloaded model [{}]", name)
