"""向社区中心投稿墙读写代理。"""

from __future__ import annotations

from typing import Any

import httpx
from nonebot import logger

from pallas.product.community_stats.config import get_community_stats_config
from pallas.product.community_stats.endpoints import gallery_posts_urls_for_config
from pallas.product.community_stats.store import load_or_create_deployment_id
from pallas.product.corpus.config import resolved_community_token
from pallas.product.message_scrub.quiet_http_loggers import scrub_http_log_noise

_TIMEOUT_SEC = 20.0


def _auth_headers() -> dict[str, str]:
    token = resolved_community_token()
    if not token:
        cfg = get_community_stats_config()
        token = str(cfg.token or "").strip()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


async def list_gallery_posts(*, limit: int = 48, mine: bool = False) -> dict[str, Any]:
    cfg = get_community_stats_config()
    urls = gallery_posts_urls_for_config(cfg)
    if not urls:
        raise RuntimeError("gallery endpoint unavailable")
    params: dict[str, Any] = {"limit": limit}
    if mine:
        params["deployment_id"] = load_or_create_deployment_id()
    scrub_http_log_noise()
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
        for url in urls:
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    return data
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.debug("community gallery list failed url={} err={}", url, e)
    raise RuntimeError(f"gallery list failed: {last_err}")


async def create_gallery_post(
    *,
    text: str,
    nickname: str,
    avatar_url: str = "",
    bot_qq: int | None = None,
    source: str = "manual",
    keywords: str = "",
    image_bytes: bytes | None = None,
    image_filename: str | None = None,
    image_content_type: str | None = None,
) -> dict[str, Any]:
    cfg = get_community_stats_config()
    urls = gallery_posts_urls_for_config(cfg)
    if not urls:
        raise RuntimeError("gallery endpoint unavailable")
    dep = load_or_create_deployment_id()
    headers = _auth_headers()
    data = {
        "deployment_id": dep,
        "text": text or "",
        "nickname": nickname or "",
        "avatar_url": avatar_url or "",
        "source": source or "manual",
        "keywords": keywords or "",
    }
    if bot_qq is not None:
        data["bot_qq"] = str(int(bot_qq))
    files = None
    if image_bytes:
        files = {
            "image": (
                image_filename or "upload.bin",
                image_bytes,
                image_content_type or "application/octet-stream",
            )
        }
    scrub_http_log_noise()
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
        for url in urls:
            try:
                resp = await client.post(url, data=data, files=files, headers=headers)
                if resp.status_code >= 400:
                    detail = resp.text[:240]
                    raise RuntimeError(f"gallery create HTTP {resp.status_code}: {detail}")
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.debug("community gallery create failed url={} err={}", url, e)
    raise RuntimeError(f"gallery create failed: {last_err}")


async def delete_gallery_post(post_id: str) -> dict[str, Any]:
    cfg = get_community_stats_config()
    urls = gallery_posts_urls_for_config(cfg)
    if not urls:
        raise RuntimeError("gallery endpoint unavailable")
    dep = load_or_create_deployment_id()
    headers = _auth_headers()
    scrub_http_log_noise()
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
        for base in urls:
            url = f"{base.rstrip('/')}/{post_id.strip()}"
            try:
                resp = await client.delete(url, params={"deployment_id": dep}, headers=headers)
                if resp.status_code >= 400:
                    raise RuntimeError(f"gallery delete HTTP {resp.status_code}: {resp.text[:240]}")
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.debug("community gallery delete failed url={} err={}", url, e)
    raise RuntimeError(f"gallery delete failed: {last_err}")
