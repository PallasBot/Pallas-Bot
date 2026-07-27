"""Pallas-Bot WebUI console API: logs routes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from .console_read_cache import cached_read
from .extended_common import (
    shard_hub_console,
)

if TYPE_CHECKING:
    from .config import Config

from packages.pb_webui.console_openapi_models import LogsData, _ApiOkResponse
from pallas.console.web.bot_web import LogScope  # noqa: TC001

from .console_metrics_runtime import _ensure_log_sink


def register_logs_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(
        f"{x}/logs",
        include_in_schema=True,
        response_model=_ApiOkResponse[LogsData],
    )
    async def _logs(
        n: int = Query(default=200, ge=1, le=plugin_config.pallas_webui_log_lines_max),
        scope: Annotated[
            LogScope,
            Query(
                description=(
                    "all=全部（分片 hub 时合并 hub 环与各 worker 落盘日志）；"
                    "webui=pallas_webui 或 [pallas-webui]；"
                    "protocol=pallas_protocol 或 [pallas-protocol]"
                ),
            ),
        ] = "all",
        source: str | None = Query(
            default=None,
            description="分片来源：all|hub|worker-0|worker-1…（默认 all，不含 bootstrap）",
        ),
    ) -> dict[str, Any]:
        _ensure_log_sink()
        from pallas.console.web import tail_nonebot_log_entries_scoped, tail_nonebot_log_lines_scoped

        src = (source or "all").strip() or "all"
        scope_norm = scope
        n_cap = n

        async def _load() -> dict[str, Any]:
            sharded_logs = False
            log_sources: list[str] = []
            try:
                if shard_hub_console():
                    sharded_logs = True
                    from pallas.core.platform.shard.logs.view import list_shard_log_sources

                    log_sources = list_shard_log_sources()
            except Exception:
                pass

            def _sync() -> dict[str, Any]:
                return {
                    "lines": tail_nonebot_log_lines_scoped(n_cap, scope_norm, source=src),
                    "entries": tail_nonebot_log_entries_scoped(n_cap, scope_norm, source=src),
                    "max": plugin_config.pallas_webui_log_lines_max,
                    "scope": scope_norm,
                    "source": src,
                    "sharded_logs": sharded_logs,
                    "log_sources": log_sources,
                }

            return await asyncio.to_thread(_sync)

        cache_key = f"logs:{n_cap}:{scope_norm}:{src}"
        data = await cached_read(key=cache_key, loader=_load, ttl_sec=0.75, stale_sec=6.0)
        return {"ok": True, "data": data}

    @router.get(
        f"{x}/logs/stream",
        include_in_schema=True,
    )
    async def _logs_stream(
        scope: Annotated[
            LogScope,
            Query(
                description=("all=全部；webui=仅 pallas_webui 相关；protocol=仅 pallas_protocol 相关"),
            ),
        ] = "all",
        source: str | None = Query(
            default=None,
            description="分片来源：all|hub|worker-N（与 GET /logs 一致）",
        ),
        last_event_id: int | None = Query(
            default=None,
            description="断点续传：仅发送 id 大于该值的日志条目",
        ),
        last_event_id_header: int | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        _ensure_log_sink()
        from pallas.console.web import iter_nonebot_log_sse

        src = (source or "all").strip() or "all"
        resume_id = last_event_id if last_event_id is not None else last_event_id_header
        return StreamingResponse(
            iter_nonebot_log_sse(scope, source=src, last_event_id=resume_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
