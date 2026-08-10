"""将构建产物挂到 webui_public_path()（默认 public-react）；子路径为文件时直出，否则回退 SPA。"""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from nonebot import logger
from starlette import status

from packages.pb_webui.data_dir import pb_webui_data_dir
from pallas.console.webui.console_login import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SEC,
    install_pallas_http_request_context_middleware,
    verify_session_token,
)

if TYPE_CHECKING:
    from .config import Config

_PLACEHOLDER_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Pallas-Bot 控制台</title>
</head>
<body style="font-family: system-ui, sans-serif; padding: 2rem">
  <h1>Pallas-Bot 控制台</h1>
  <p>尚未部署前端资源。请将构建产物放入 <code>data/pb_webui/public-react</code>（默认 React）
  或 <code>data/pb_webui/public</code>（Vue），
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
    plugin_config: Config,
) -> None:
    install_pallas_http_request_context_middleware(app)
    base = (base or "/pallas").strip()
    if not base.startswith("/"):
        base = "/" + base
    base = base.rstrip("/")

    def dev_mode_active() -> bool:
        return bool(getattr(plugin_config, "pallas_webui_dev_mode", False))

    root_resolved = public_dir.resolve()
    legacy_page_cookie = "pallas_webui_page_token"

    def _is_token_valid(token: str | None) -> bool:
        return bool((token or "").strip()) and verify_session_token(token)

    def _request_token(request: Request, query_token: str | None) -> str:
        c = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
        if c:
            return c
        return (query_token or request.cookies.get(legacy_page_cookie) or "").strip()

    def _refresh_page_cookie(response: FileResponse | RedirectResponse, request: Request, token: str) -> None:
        if not verify_session_token(token):
            return
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=SESSION_TTL_SEC,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )

    def _login_redirect(next_path: str, *, reason: str = "") -> RedirectResponse:
        encoded_next = quote(next_path, safe="/?=&-_.~")
        if reason:
            encoded_reason = quote(reason, safe="")
            return RedirectResponse(url=f"{base}/login?next={encoded_next}&reason={encoded_reason}", status_code=307)
        return RedirectResponse(url=f"{base}/login?next={encoded_next}", status_code=307)

    def _pick_static_target(raw_path: str) -> Path | None:
        """同步 IO：在 root_resolved 内挑选要响应的静态文件；越界一律返回 None。"""
        normalized = posixpath.normpath("/" + raw_path).lstrip("/")
        try:
            candidate = (public_dir / normalized).resolve()
        except (OSError, RuntimeError):
            return None
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            return None
        if candidate.is_file():
            return candidate
        if candidate.is_dir():
            inner = candidate / "index.html"
            if inner.is_file():
                return inner
        return None

    def _pick_index_fallback() -> Path | None:
        idx = public_dir / "index.html"
        return idx if idx.is_file() else None

    router = APIRouter()

    shared_pallas_ui_dir = Path(__file__).resolve().parent.parent / "pb_protocol" / "web" / "static" / "pallas_ui"
    # 须在 warm_plugin_store_assets 之前挂载：目录可能尚未存在，否则 SPA catch-all 会吞掉图片 URL。
    plugin_store_assets_dir = pb_webui_data_dir(create=True) / "store-assets"
    plugin_store_assets_dir.mkdir(parents=True, exist_ok=True)
    use_priest_avatar = shared_pallas_ui_dir.is_dir()

    def _spa_file_response(path: Path) -> FileResponse:
        response = FileResponse(path)
        # SPA 入口勿被中间层/浏览器长期缓存，否则会继续引用旧 hash 的 JS。
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response

    def _spa_index_response() -> FileResponse | HTMLResponse:
        idx = public_dir / "index.html"
        if idx.is_file():
            return _spa_file_response(idx)
        logger.warning(
            "[控制台] 未找到 {}，可设置 pallas_webui_dist_zip_url 或手动放置构建产物。",
            public_dir / "index.html",
        )
        return HTMLResponse(
            content=_PLACEHOLDER_HTML,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @router.get(f"{base}/login", include_in_schema=False, response_model=None)
    async def _login() -> FileResponse | HTMLResponse:
        """鉴权豁免：出 SPA（React LoginPage）；登录走 POST /api/auth/login。"""
        return _spa_index_response()

    @router.post(f"{base}/logout", include_in_schema=False, response_model=None)
    async def _logout() -> RedirectResponse:
        response = RedirectResponse(url=f"{base}/login", status_code=303)
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
        response.delete_cookie(key=legacy_page_cookie, path=base or "/")
        return response

    @router.get(f"{base}/plugin-assets/{{plugin_id}}/{{asset_path:path}}", include_in_schema=False, response_model=None)
    async def _plugin_package_asset(plugin_id: str, asset_path: str) -> FileResponse:
        from pallas.console.webui.plugin_package_assets import resolve_plugin_package_asset_file

        path = resolve_plugin_package_asset_file(plugin_id, asset_path)
        if path is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
        return FileResponse(path)

    @router.get(
        f"{base}",
        include_in_schema=False,
        response_model=None,
    )
    async def _trailing() -> RedirectResponse:  # pragma: no cover - 路由注册
        return RedirectResponse(url=f"{base}/", status_code=307)

    @router.get(f"{base}/", include_in_schema=False, response_model=None)
    async def _index(request: Request, token: str | None = Query(default=None)) -> FileResponse | HTMLResponse:
        got = ""
        if not dev_mode_active():
            got = _request_token(request, token)
            if not got:
                return _login_redirect(str(request.url.path))
            if not _is_token_valid(got):
                return _login_redirect(
                    str(request.url.path),
                    reason="未登录或会话已失效，请重新登录",
                )
        idx = public_dir / "index.html"
        if idx.is_file():
            response = _spa_file_response(idx)
            if got and _is_token_valid(got):
                _refresh_page_cookie(response, request, got)
            return response
        logger.warning(
            "[控制台] 未找到 {}，可设置 pallas_webui_dist_zip_url 或手动放置构建产物。",
            public_dir / "index.html",
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

    readme_brand_avatar = Path(__file__).resolve().parent / "static" / "brand-avatar.png"

    @router.get(f"{base}/assets/brand-avatar.png", include_in_schema=False, response_model=None)
    async def _readme_brand_avatar() -> FileResponse:
        if readme_brand_avatar.is_file():
            return FileResponse(readme_brand_avatar)
        fallback = public_dir / "assets" / "brand-avatar.png"
        if fallback.is_file():
            return FileResponse(fallback)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="brand avatar not found")

    @router.get(
        f"{base}/" + "{path:path}",
        include_in_schema=False,
        response_model=None,
    )
    async def _static_or_spa(
        request: Request,
        path: str,
        token: str | None = Query(default=None),
    ) -> FileResponse | HTMLResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"JSON 接口请使用 {base}/api/，勿走静态 catch-all",
            )
        target = _pick_static_target(path)
        if target is not None:
            if target.suffix.lower() == ".html":
                if dev_mode_active():
                    return _spa_file_response(target)
                got = _request_token(request, token)
                if _is_token_valid(got):
                    response = _spa_file_response(target)
                    _refresh_page_cookie(response, request, got)
                    return response
                return _login_redirect(f"{base}/{path}", reason="请先登录后再访问页面")
            return FileResponse(target)
        fallback = _pick_index_fallback()
        if fallback is not None:
            if dev_mode_active():
                return _spa_file_response(fallback)
            got = _request_token(request, token)
            if _is_token_valid(got):
                response = _spa_file_response(fallback)
                _refresh_page_cookie(response, request, got)
                return response
            return _login_redirect(f"{base}/{path}", reason="请先登录后再访问页面")
        return HTMLResponse(
            content=_PLACEHOLDER_HTML,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if use_priest_avatar:
        app.mount(
            f"{base}/_pallas_ui",
            StaticFiles(directory=str(shared_pallas_ui_dir)),
            name="pallas_webui_pallas_ui",
        )

    app.mount(
        f"{base}/store-assets",
        StaticFiles(directory=str(plugin_store_assets_dir)),
        name="pallas_webui_store_assets",
    )

    app.include_router(router)
