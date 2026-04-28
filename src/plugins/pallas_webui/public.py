"""将构建产物（如 Vite dist）挂到 data/pallas_webui/public；子路径为文件时直出，否则回退 SPA。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from nonebot import logger
from starlette import status

if TYPE_CHECKING:
    from pathlib import Path

_PLACEHOLDER_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Pallas 控制台</title>
</head>
<body style="font-family: system-ui, sans-serif; padding: 2rem">
  <h1>Pallas 控制台</h1>
  <p>尚未部署前端资源。请将 Vite 等构建产物放入 <code>data/pallas_webui/public</code>，
  或设置 <code>pallas_webui_dist_zip_url</code> 为 dist 的 zip 直链，由插件在启动时自动解压。</p>
  <p>API 探测请访问 <a href="api/health">api/health</a>（相对本页，即
  控制台基址 + <code>/api/health</code>)。</p>
  </body>
</html>
"""


def register_routes(
    app,
    *,
    public_dir: Path,
    base: str,
) -> None:
    base = (base or "/pallas").strip()
    if not base.startswith("/"):
        base = "/" + base
    base = base.rstrip("/")

    router = APIRouter()

    @router.get(
        f"{base}",
        include_in_schema=False,
        response_model=None,
    )
    async def _trailing() -> RedirectResponse:  # pragma: no cover - 路由注册
        return RedirectResponse(url=f"{base}/", status_code=307)

    @router.get(f"{base}/", include_in_schema=False, response_model=None)
    async def _index() -> FileResponse | HTMLResponse:
        idx = public_dir / "index.html"
        if idx.is_file():
            return FileResponse(idx)
        logger.warning(
            f"Pallas 控制台: 未找到 {public_dir / 'index.html'}，可设置 pallas_webui_dist_zip_url 或手动放置构建产物。",
        )
        return HTMLResponse(
            content=_PLACEHOLDER_HTML,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @router.get(f"{base}/favicon.ico", include_in_schema=False, response_model=None)
    async def _favicon() -> FileResponse:
        ico = public_dir / "favicon.ico"
        if not ico.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no favicon")
        return FileResponse(ico)

    @router.get(
        f"{base}/" + "{path:path}",
        include_in_schema=False,
        response_model=None,
    )
    async def _static_or_spa(path: str) -> FileResponse | HTMLResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"JSON 接口请使用 {base}/api/，勿走静态 catch-all",
            )
        candidate = public_dir / path
        if candidate.is_file():
            return FileResponse(candidate)
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return FileResponse(candidate / "index.html")
        idx = public_dir / "index.html"
        if idx.is_file():
            return FileResponse(idx)
        return HTMLResponse(
            content=_PLACEHOLDER_HTML,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # 注册静态路由
    app.include_router(router)
