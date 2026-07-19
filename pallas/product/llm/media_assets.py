"""代理 Pallas-Bot-AI 媒体权重 status / download。"""

from __future__ import annotations

from typing import Any

from pallas.core.shared.utils import HTTPXClient
from pallas.product.llm.config import LlmConfig, get_llm_config, llm_server_base_url


def ai_media_assets_base(cfg: LlmConfig | None = None) -> str:
    return f"{llm_server_base_url(cfg or get_llm_config()).rstrip('/')}/api/media/assets"


async def fetch_media_assets_status(*, cfg: LlmConfig | None = None, timeout_sec: float = 12.0) -> dict[str, Any]:
    url = f"{ai_media_assets_base(cfg)}/status"
    try:
        response = await HTTPXClient.get(url, timeout=timeout_sec)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "deploy_mode": "unknown",
            "assets": {},
            "media_packages_enabled": {},
            "all_media_assets_ready": False,
            "download_allowed": False,
            "hints": ["ai_unreachable"],
        }
    if response is None or response.status_code != 200:
        code = response.status_code if response is not None else None
        return {
            "ok": False,
            "error": f"读取媒体权重状态失败 HTTP {code}",
            "deploy_mode": "unknown",
            "assets": {},
            "media_packages_enabled": {},
            "all_media_assets_ready": False,
            "download_allowed": False,
            "hints": ["ai_status_http_error"],
        }
    try:
        payload = response.json()
    except Exception:
        return {
            "ok": False,
            "error": "媒体权重状态响应无效",
            "deploy_mode": "unknown",
            "assets": {},
            "media_packages_enabled": {},
            "all_media_assets_ready": False,
            "download_allowed": False,
            "hints": ["ai_status_invalid"],
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "error": "媒体权重状态格式无效",
            "deploy_mode": "unknown",
            "assets": {},
            "media_packages_enabled": {},
            "all_media_assets_ready": False,
            "download_allowed": False,
            "hints": ["ai_status_invalid"],
        }
    return {"ok": True, "error": "", **payload}


async def start_media_assets_download(*, cfg: LlmConfig | None = None, timeout_sec: float = 30.0) -> dict[str, Any]:
    url = f"{ai_media_assets_base(cfg)}/download"
    try:
        response = await HTTPXClient.post(url, json={}, timeout=timeout_sec)
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    if response is None:
        raise RuntimeError("AI 服务无响应")
    if response.status_code == 409:
        detail = ""
        try:
            body = response.json()
            detail = str(body.get("detail") or body)
        except Exception:
            detail = response.text or "当前部署不允许下载"
        raise PermissionError(detail)
    if response.status_code != 200:
        raise RuntimeError(f"启动下载失败 HTTP {response.status_code}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("下载任务响应无效") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("下载任务响应格式无效")
    return payload


async def fetch_media_assets_download_job(
    job_id: str, *, cfg: LlmConfig | None = None, timeout_sec: float = 12.0
) -> dict[str, Any]:
    url = f"{ai_media_assets_base(cfg)}/download/jobs/{job_id.strip()}"
    try:
        response = await HTTPXClient.get(url, timeout=timeout_sec)
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    if response is None or response.status_code == 404:
        raise FileNotFoundError("任务不存在")
    if response.status_code != 200:
        raise RuntimeError(f"读取下载任务失败 HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("下载任务响应格式无效")
    return payload
