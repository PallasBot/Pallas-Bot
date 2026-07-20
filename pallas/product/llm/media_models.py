"""代理 Pallas-Bot-AI 唱歌/TTS 模型清单与默认项。"""

from __future__ import annotations

from typing import Any

import httpx

from pallas.product.llm.config import LlmConfig, get_llm_config, llm_server_base_url


def ai_media_models_base(cfg: LlmConfig | None = None) -> str:
    return f"{llm_server_base_url(cfg or get_llm_config()).rstrip('/')}/api/media/models"


def _detail_from_response(response: httpx.Response, fallback: str) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("detail") is not None:
            return str(body.get("detail"))
    except Exception:
        pass
    text = (response.text or "").strip()
    return text or fallback


async def _proxy_get(path: str, *, cfg: LlmConfig | None = None, timeout_sec: float = 12.0) -> dict[str, Any]:
    url = f"{ai_media_models_base(cfg)}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.get(url)
    except Exception as exc:
        raise RuntimeError(f"AI Runtime 不可达：{exc}") from exc
    if response.status_code == 404:
        raise RuntimeError("AI Runtime 缺少媒体模型接口（/api/media/models）。请更新并重启 Pallas-Bot-AI 后再刷新。")
    if response.status_code != 200:
        raise RuntimeError(_detail_from_response(response, f"请求失败 HTTP {response.status_code}"))
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("响应无效") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("响应格式无效")
    return payload


async def _proxy_put(
    path: str,
    body: dict[str, Any],
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 12.0,
) -> dict[str, Any]:
    url = f"{ai_media_models_base(cfg)}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.put(url, json=body)
    except Exception as exc:
        raise RuntimeError(f"AI Runtime 不可达：{exc}") from exc
    if response.status_code == 404:
        raise RuntimeError("AI Runtime 缺少媒体模型接口（/api/media/models）。请更新并重启 Pallas-Bot-AI 后再试。")
    if response.status_code == 409:
        raise PermissionError(_detail_from_response(response, "当前部署不允许写入"))
    if response.status_code == 400:
        raise ValueError(_detail_from_response(response, "参数无效"))
    if response.status_code != 200:
        raise RuntimeError(_detail_from_response(response, f"保存失败 HTTP {response.status_code}"))
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("响应无效") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("响应格式无效")
    return payload


async def fetch_sing_speakers(*, cfg: LlmConfig | None = None) -> dict[str, Any]:
    return await _proxy_get("/sing/speakers", cfg=cfg)


async def fetch_sing_backends(*, cfg: LlmConfig | None = None) -> dict[str, Any]:
    return await _proxy_get("/sing/backends", cfg=cfg)


async def fetch_sing_defaults(*, cfg: LlmConfig | None = None) -> dict[str, Any]:
    return await _proxy_get("/sing/defaults", cfg=cfg)


async def put_sing_defaults(
    body: dict[str, Any],
    *,
    cfg: LlmConfig | None = None,
) -> dict[str, Any]:
    return await _proxy_put("/sing/defaults", body, cfg=cfg)


async def fetch_tts_voices(*, cfg: LlmConfig | None = None) -> dict[str, Any]:
    return await _proxy_get("/tts/voices", cfg=cfg)


async def fetch_tts_defaults(*, cfg: LlmConfig | None = None) -> dict[str, Any]:
    return await _proxy_get("/tts/defaults", cfg=cfg)


async def put_tts_defaults(body: dict[str, Any], *, cfg: LlmConfig | None = None) -> dict[str, Any]:
    return await _proxy_put("/tts/defaults", body, cfg=cfg)
