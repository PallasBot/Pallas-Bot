"""Pallas-Bot WebUI console API: stats dashboard HTTP routes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from nonebot import logger
from pydantic import BaseModel, Field

from packages.pb_webui.console_openapi_models import _ApiOkResponse

from .console_read_cache import cached_read
from .extended_common import (
    check_pallas_write_token,
)

if TYPE_CHECKING:
    from .config import Config

from .console_metrics_runtime import (
    _cleanup_log_errors_manual_sync,
    _console_daily_stats_payload,
    _log_errors_payload,
    _message_stats_overview,
    _plugin_run_stats_overview,
)


class CommunityConnectivityCheckData(BaseModel):
    probes: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    reporting: dict[str, Any] = Field(default_factory=dict)


def register_stats_dashboard_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(f"{x}/message-stats", include_in_schema=True)
    async def _message_stats(
        self_id: int | None = Query(default=None, ge=1),
    ) -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return await _message_stats_overview(self_id=str(self_id) if self_id is not None else None)

        key = f"message-stats:{self_id or 'all'}"
        ttl = 4.0 if self_id is not None else 2.0
        stale = 15.0 if self_id is not None else 10.0
        data = await cached_read(key=key, loader=_load, ttl_sec=ttl, stale_sec=stale)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/community-stats", include_in_schema=True)
    async def _community_stats() -> JSONResponse:
        from pallas.core.shared.utils.format_exception import format_exception_for_log
        from pallas.product.community_stats.public_stats import fetch_community_public_stats

        async def _load() -> dict[str, Any]:
            return await fetch_community_public_stats()

        try:
            data = await cached_read(key="community-stats", loader=_load, ttl_sec=30.0, stale_sec=120.0)
        except Exception as e:  # noqa: BLE001
            logger.warning("community-stats: {}", format_exception_for_log(e))
            raise HTTPException(status_code=502, detail=format_exception_for_log(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(
        f"{x}/community-stats/connectivity-check",
        include_in_schema=True,
        response_model=_ApiOkResponse[CommunityConnectivityCheckData],
    )
    async def _community_stats_connectivity_check(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> dict[str, Any]:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.community_stats.connectivity_probe import probe_community_connectivity

        try:
            data = await probe_community_connectivity()
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 社区连通检测失败")
            raise HTTPException(status_code=500, detail="社区连通检测失败") from e
        return {"ok": True, "data": data}

    @router.get(f"{x}/community-corpus-hot", include_in_schema=True)
    async def _community_corpus_hot(
        mode: str = Query(default="fleet"),
        period: str = Query(default="day"),
        limit: int = Query(default=40, ge=5, le=80),
    ) -> JSONResponse:
        from pallas.product.community_stats.public_stats import fetch_community_corpus_hot

        mode_norm = mode if mode in {"pool", "recent", "fleet"} else "fleet"
        period_norm = period if period in {"day", "week", "month"} else "day"

        async def _load() -> dict[str, Any]:
            return await fetch_community_corpus_hot(mode=mode_norm, period=period_norm, limit=limit)

        cache_key = f"community-corpus-hot:{mode_norm}:{period_norm}:{limit}"
        data = await cached_read(key=cache_key, loader=_load, ttl_sec=120.0, stale_sec=300.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/community-gallery", include_in_schema=True)
    async def _community_gallery_list(
        limit: int = Query(default=48, ge=1, le=100),
        mine: bool = Query(default=False),
    ) -> JSONResponse:
        from pallas.product.community_stats.gallery_client import list_gallery_posts

        try:
            data = await list_gallery_posts(limit=limit, mine=mine)
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 社区投稿列表失败")
            raise HTTPException(status_code=502, detail=f"社区投稿列表失败: {e}") from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/community-gallery", include_in_schema=True)
    async def _community_gallery_create(
        text: str = Form(default=""),
        nickname: str = Form(default=""),
        avatar_url: str = Form(default=""),
        bot_qq: int | None = Form(default=None),
        source: str = Form(default="manual"),
        keywords: str = Form(default=""),
        image: UploadFile | None = File(default=None),  # noqa: B008
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.community_stats.gallery_client import create_gallery_post

        image_bytes = None
        image_filename = None
        image_content_type = None
        if image is not None and image.filename:
            image_bytes = await image.read()
            image_filename = image.filename
            image_content_type = image.content_type
        try:
            data = await create_gallery_post(
                text=text,
                nickname=(nickname or "").strip() or "牛牛",
                avatar_url=avatar_url,
                bot_qq=bot_qq,
                source=source,
                keywords=keywords,
                image_bytes=image_bytes,
                image_filename=image_filename,
                image_content_type=image_content_type,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 社区投稿失败")
            raise HTTPException(status_code=502, detail=f"社区投稿失败: {e}") from e
        return JSONResponse({"ok": True, "data": data})

    @router.delete(f"{x}/community-gallery/{{post_id}}", include_in_schema=True)
    async def _community_gallery_delete(
        post_id: str,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.community_stats.gallery_client import delete_gallery_post

        try:
            data = await delete_gallery_post(post_id)
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 社区投稿撤下失败")
            raise HTTPException(status_code=502, detail=f"社区投稿撤下失败: {e}") from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/local-corpus-hot", include_in_schema=True)
    async def _local_corpus_hot(
        scope: str = Query(default="global"),
        group_id: int | None = Query(default=None),
        limit: int = Query(default=40, ge=5, le=80),
    ) -> JSONResponse:
        from pallas.product.corpus.local_hot import aggregate_local_hot_keywords, build_local_corpus_hot_payload

        scope_norm = scope if scope in {"global", "group"} else "global"
        gid = int(group_id) if scope_norm == "group" and group_id is not None else 0

        async def _load() -> dict[str, Any]:
            items = await aggregate_local_hot_keywords(scope=scope_norm, group_id=group_id, limit=limit)
            return build_local_corpus_hot_payload(items)

        cache_key = f"local-corpus-hot:{scope_norm}:{gid}:{limit}"
        data = await cached_read(key=cache_key, loader=_load, ttl_sec=60.0, stale_sec=180.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/corpus-status", include_in_schema=True)
    async def _corpus_status() -> JSONResponse:
        from pallas.product.corpus.status import build_corpus_status_snapshot

        async def _load() -> dict[str, Any]:
            return await build_corpus_status_snapshot()

        data = await cached_read(key="corpus-status", loader=_load, ttl_sec=15.0, stale_sec=90.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/federation-onboarding", include_in_schema=True)
    async def _federation_onboarding() -> JSONResponse:
        from pallas.product.community_stats.federation_onboarding import fetch_federation_onboarding

        async def _load() -> dict[str, Any]:
            return await fetch_federation_onboarding()

        try:
            data = await cached_read(
                key="federation-onboarding",
                loader=_load,
                ttl_sec=120.0,
                stale_sec=600.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Pallas-Bot 控制台: 拉取联邦入池说明失败 err={}", e)
            raise HTTPException(status_code=502, detail="无法从社区中心拉取联邦入池说明") from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/plugin-run-stats", include_in_schema=True)
    async def _plugin_run_stats(
        self_id: int | None = Query(default=None, ge=1),
        log_source: str | None = Query(
            default=None,
            description="日志报错来源筛选：all|hub|worker-N",
        ),
        tb_limit: int = Query(
            default=0,
            ge=0,
            le=200_000,
            description="log_error_log 单条 traceback 最大字符数，0 表示不截断",
        ),
        view: str | None = Query(
            default=None,
            description="log_errors 时仅返回 log_error_log 与来源元数据，跳过 Bot 统计聚合",
        ),
    ) -> JSONResponse:
        src = (log_source or "all").strip() or "all"
        view_norm = (view or "").strip().lower()

        async def _load() -> dict[str, Any]:
            if view_norm == "log_errors":
                return await asyncio.to_thread(
                    _log_errors_payload,
                    source=src,
                    tb_limit=tb_limit,
                )
            include_log_errors = self_id is None
            return await asyncio.to_thread(
                _plugin_run_stats_overview,
                self_id=str(self_id) if self_id is not None else None,
                log_source=src,
                tb_limit=tb_limit,
                include_log_errors=include_log_errors,
            )

        key = f"plugin-run-stats:{self_id or 'all'}:logsrc:{src}:tbl:{tb_limit}:view:{view_norm or 'full'}"
        ttl = 3.0 if view_norm == "log_errors" or self_id is not None else 2.0
        stale = 20.0 if view_norm == "log_errors" else 12.0 if self_id is not None else 10.0
        data = await cached_read(key=key, loader=_load, ttl_sec=ttl, stale_sec=stale)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/log-errors", include_in_schema=True)
    async def _log_errors(
        log_source: str | None = Query(
            default=None,
            description="报错来源筛选：all|hub|worker-N",
        ),
        tb_limit: int = Query(
            default=0,
            ge=0,
            le=200_000,
            description="单条 traceback 最大字符数，0 表示不截断",
        ),
        limit: int = Query(default=120, ge=1, le=500, description="最多返回条数"),
    ) -> JSONResponse:
        src = (log_source or "all").strip() or "all"

        async def _load() -> dict[str, Any]:
            return await asyncio.to_thread(
                _log_errors_payload,
                source=src,
                tb_limit=tb_limit,
                limit=limit,
            )

        key = f"log-errors:logsrc:{src}:tbl:{tb_limit}:lim:{limit}"
        data = await cached_read(key=key, loader=_load, ttl_sec=3.0, stale_sec=25.0)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/log-errors/cleanup", include_in_schema=True)
    async def _log_errors_cleanup() -> JSONResponse:
        """清空日志报错归档。"""
        try:
            data = await asyncio.to_thread(_cleanup_log_errors_manual_sync)
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 清理日志报错失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        logger.info("Pallas-Bot 控制台: 已手动清理日志报错归档")
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/console-daily-stats", include_in_schema=True)
    async def _console_daily_stats(
        self_id: int | None = Query(default=None, ge=1),
        start: str | None = Query(default=None, description="YYYY-MM-DD，含当日"),
        end: str | None = Query(default=None, description="YYYY-MM-DD，含当日"),
    ) -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return await asyncio.to_thread(
                _console_daily_stats_payload,
                self_id=str(self_id) if self_id is not None else None,
                start=start,
                end=end,
            )

        key = f"console-daily-stats:{self_id or 'all'}:{start or ''}:{end or ''}"
        data = await cached_read(key=key, loader=_load, ttl_sec=3.5, stale_sec=18.0)
        return JSONResponse({"ok": True, "data": data})
