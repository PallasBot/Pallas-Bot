"""将构建产物（如 Vite dist）挂到 data/pallas_webui/public；子路径为文件时直出，否则回退 SPA。"""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from nonebot import logger
from starlette import status

from src.common.pallas_console_login import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SEC,
    install_pallas_http_request_context_middleware,
    mint_session_token,
    verify_console_password,
    verify_session_token,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .config import Config

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
    plugin_config: Config,
) -> None:
    install_pallas_http_request_context_middleware(app)
    base = (base or "/pallas").strip()
    if not base.startswith("/"):
        base = "/" + base
    base = base.rstrip("/")
    dev_mode = bool(getattr(plugin_config, "pallas_webui_dev_mode", False))

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

    def _resolve_login_target(next_path: str | None) -> str:
        target = (next_path or f"{base}/").strip() or f"{base}/"
        if not target.startswith(base):
            target = f"{base}/"
        return target

    def _render_login_page(*, target: str, reason: str | None, token_submitted: bool) -> HTMLResponse:
        from src.common.pallas_login_page import render_pallas_login_page_html

        err = (reason or "").strip()
        if token_submitted:
            err = "口令无效，请重试。"
        html = render_pallas_login_page_html(
            document_title="控制台登录 · Pallas",
            surface_label="控制台",
            tagline="与协议端管理共用口令。",
            form_action=f"{base}/login",
            next_path=target,
            error_message=err,
            head_extra_html="",
            footer_note="",
            favicon_variant="console",
        )
        return HTMLResponse(html)

    @router.get(f"{base}/login", include_in_schema=False, response_model=None)
    async def _login(
        next_path: str | None = Query(default=None, alias="next"),
        reason: str | None = Query(default=None),
    ) -> HTMLResponse:
        target = _resolve_login_target(next_path)
        return _render_login_page(target=target, reason=reason, token_submitted=False)

    @router.post(f"{base}/login", include_in_schema=False, response_model=None)
    async def _login_submit(
        request: Request,
        next_path: str | None = Form(default=None, alias="next"),
        token: str = Form(...),
    ) -> RedirectResponse | HTMLResponse:
        target = _resolve_login_target(next_path)
        if verify_console_password(token):
            sess = mint_session_token()
            response = RedirectResponse(url=target, status_code=303)
            response.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=sess,
                max_age=SESSION_TTL_SEC,
                httponly=True,
                samesite="lax",
                secure=request.url.scheme == "https",
                path="/",
            )
            response.delete_cookie(key=legacy_page_cookie, path=base or "/")
            return response
        return _render_login_page(target=target, reason=None, token_submitted=True)

    @router.post(f"{base}/logout", include_in_schema=False, response_model=None)
    async def _logout() -> RedirectResponse:
        response = RedirectResponse(url=f"{base}/login", status_code=303)
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
        response.delete_cookie(key=legacy_page_cookie, path=base or "/")
        return response

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
        if not dev_mode:
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
            response = FileResponse(idx)
            if got and _is_token_valid(got):
                _refresh_page_cookie(response, request, got)
            return response
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
                if dev_mode:
                    return FileResponse(target)
                got = _request_token(request, token)
                if _is_token_valid(got):
                    response = FileResponse(target)
                    _refresh_page_cookie(response, request, got)
                    return response
                return _login_redirect(f"{base}/{path}", reason="请先登录后再访问页面")
            return FileResponse(target)
        fallback = _pick_index_fallback()
        if fallback is not None:
            if dev_mode:
                return FileResponse(fallback)
            got = _request_token(request, token)
            if _is_token_valid(got):
                response = FileResponse(fallback)
                _refresh_page_cookie(response, request, got)
                return response
            return _login_redirect(f"{base}/{path}", reason="请先登录后再访问页面")
        return HTMLResponse(
            content=_PLACEHOLDER_HTML,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # 注册静态路由
    app.include_router(router)
