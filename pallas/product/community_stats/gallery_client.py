"""向社区中心投稿墙读写代理。"""

from __future__ import annotations

from typing import Any

import httpx
from nonebot import logger

from pallas.product.community_stats.config import get_community_stats_config
from pallas.product.community_stats.endpoints import gallery_posts_urls_for_config
from pallas.product.community_stats.store import (
    add_local_gallery_post,
    load_local_gallery_posts,
    load_or_create_deployment_id,
    remove_local_gallery_post,
)
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


def _local_list_payload(mine: bool) -> dict[str, Any]:
    posts = load_local_gallery_posts()
    if not mine:
        posts = [p for p in posts if p.get("source") == "manual"]
    return {"as_of": None, "posts": posts, "next_cursor": None, "did_fail": True}


async def _list_remote(limit: int, mine: bool) -> dict[str, Any] | None:
    cfg = get_community_stats_config()
    urls = gallery_posts_urls_for_config(cfg)
    if not urls:
        return None
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
                logger.debug("Community gallery listing failed for URL [{}]: [{}]", url, e)
    logger.debug("Community gallery remote listing failed, falling back to local: [{}]", last_err)
    return None


async def list_gallery_posts(*, limit: int = 48, mine: bool = False) -> dict[str, Any]:
    remote = await _list_remote(limit=limit, mine=mine)
    if remote is not None:
        return remote
    return _local_list_payload(mine=mine)


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
    remote_payload: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
        for url in urls:
            try:
                resp = await client.post(url, data=data, files=files, headers=_auth_headers())
                if resp.status_code >= 400:
                    detail = resp.text[:240]
                    raise RuntimeError(f"gallery create HTTP {resp.status_code}: {detail}")
                payload = resp.json()
                if isinstance(payload, dict):
                    remote_payload = payload
                    break
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.debug("Community gallery creation failed for URL [{}]: [{}]", url, e)
    post_fields = dict(data)
    if bot_qq is not None:
        post_fields["bot_qq"] = int(bot_qq)
    else:
        post_fields.pop("bot_qq", None)
    remote_id = (remote_payload or {}).get("id") if remote_payload else None
    if remote_id:
        post_fields["id"] = str(remote_id)
    local = add_local_gallery_post(**post_fields)
    if remote_payload:
        return remote_payload
    logger.debug("Community gallery remote creation failed, kept local copy: [{}]", last_err)
    return local


async def delete_gallery_post(post_id: str) -> dict[str, Any]:
    cfg = get_community_stats_config()
    urls = gallery_posts_urls_for_config(cfg)
    dep = load_or_create_deployment_id()
    remove_local_gallery_post(post_id)
    if not urls:
        return {"ok": True, "id": post_id}
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
                logger.debug("Community gallery deletion failed for URL [{}]: [{}]", url, e)
    logger.debug("Community gallery remote deletion failed, kept local removal: [{}]", last_err)
    return {"ok": True, "id": post_id}
