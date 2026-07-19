"""控制台帮助图预览 API。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .preview import render_help_preview_bytes


def register_help_preview_routes(router: APIRouter, *, api_base: str) -> None:
    prefix = (api_base or "/pallas/api").rstrip("/")

    @router.get(f"{prefix}/help/preview", include_in_schema=True)
    async def help_preview(
        level: Literal["menu", "plugin", "function"] = Query(default="menu"),
        page: int = Query(default=1, ge=1),
        plugin: str | None = Query(default=None),
        function: str | None = Query(default=None),
        show_ignored: bool = Query(default=False),
    ) -> Response:
        try:
            image_bytes = await render_help_preview_bytes(
                level=level,  # type: ignore[arg-type]
                page=page,
                plugin=plugin,
                function=function,
                show_ignored=show_ignored,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=image_bytes, media_type="image/png")
