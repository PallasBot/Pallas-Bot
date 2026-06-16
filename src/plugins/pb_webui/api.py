"""Pallas-Bot 控制台 JSON API 前缀；健康检查等轻量路由可在此注册或再拆子路由。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from nonebot import __version__ as _nb_ver
from nonebot import get_driver, logger

from src.foundation.bot_version import get_pallas_bot_version_for_health

from .console_meta_store import get_console_meta, merge_console_version_from_disk

_HEALTH_REFRESH_SEC = 30.0
_health_snapshot: dict[str, Any] | None = None
_health_refresh_task: asyncio.Task[None] | None = None


def _build_health_payload(
    *,
    console_meta: dict[str, Any],
    static_root: Path | None,
    pallas_ver: str,
) -> dict[str, Any]:
    live_console = {**console_meta, **get_console_meta()}
    merge_console_version_from_disk(live_console, static_root)
    return {
        "ok": True,
        "nonebot2": str(_nb_ver),
        "pallas_bot": pallas_ver,
        "console": live_console,
    }


async def refresh_health_snapshot(
    *,
    console_meta: dict[str, Any],
    static_root: Path | None,
    pallas_ver: str,
) -> dict[str, Any]:
    global _health_snapshot
    payload = await asyncio.to_thread(
        _build_health_payload,
        console_meta=console_meta,
        static_root=static_root,
        pallas_ver=pallas_ver,
    )
    _health_snapshot = payload
    return payload


def invalidate_health_snapshot() -> None:
    """WebUI 更新或 console 元信息变更后丢弃缓存，下次 /health 立即重读 dist。"""
    global _health_snapshot
    _health_snapshot = None


def register_api(
    app,
    *,
    api_base: str,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    """api_base 为完整前缀，例如 /pallas/api 。"""
    x = (api_base or "/pallas/api").strip()
    if not x.startswith("/"):
        x = "/" + x
    x = x.rstrip("/")  # /pallas/api

    router = APIRouter(tags=["Pallas-Bot 控制台"])

    console_meta = dict(extra_meta or {})
    static_root = Path(str(console_meta.get("static_root", "")).strip()) if console_meta.get("static_root") else None
    merge_console_version_from_disk(console_meta, static_root)

    pallas_ver = get_pallas_bot_version_for_health()
    driver = get_driver()

    async def health_refresh_loop() -> None:
        while True:
            await asyncio.sleep(_HEALTH_REFRESH_SEC)
            try:
                await refresh_health_snapshot(
                    console_meta=console_meta,
                    static_root=static_root,
                    pallas_ver=pallas_ver,
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("pallas_webui health cache refresh failed: {}", e)

    @driver.on_startup
    async def _health_cache_startup() -> None:
        global _health_refresh_task
        await refresh_health_snapshot(
            console_meta=console_meta,
            static_root=static_root,
            pallas_ver=pallas_ver,
        )
        _health_refresh_task = asyncio.create_task(
            health_refresh_loop(),
            name="pallas_webui_health_cache",
        )

    @driver.on_shutdown
    async def _health_cache_shutdown() -> None:
        global _health_refresh_task
        task = _health_refresh_task
        _health_refresh_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @router.get(f"{x}/health", include_in_schema=True)
    async def _health() -> JSONResponse:  # pragma: no cover - 路由注册
        snap = _health_snapshot
        if snap is None:
            snap = await refresh_health_snapshot(
                console_meta=console_meta,
                static_root=static_root,
                pallas_ver=pallas_ver,
            )
        return JSONResponse(snap, status_code=status.HTTP_200_OK)

    app.include_router(router)
