"""将构建产物（如 Vite dist）挂到 data/pallas_webui/public；子路径为文件时直出，否则回退 SPA。"""

from __future__ import annotations

import posixpath
from html import escape as html_escape
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Query, Request
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
    api_token: str,
) -> None:
    base = (base or "/pallas").strip()
    if not base.startswith("/"):
        base = "/" + base
    base = base.rstrip("/")

    root_resolved = public_dir.resolve()
    required_token = (api_token or "").strip()
    page_cookie_name = "pallas_webui_page_token"

    def _is_token_valid(token: str | None) -> bool:
        return bool(required_token) and (token or "").strip() == required_token

    def _request_token(request: Request, query_token: str | None) -> str:
        return (query_token or request.cookies.get(page_cookie_name) or "").strip()

    def _refresh_page_cookie(response: FileResponse | RedirectResponse, request: Request, token: str) -> None:
        response.set_cookie(
            key=page_cookie_name,
            value=token,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path=base or "/",
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
        detail = ""
        if not required_token:
            detail = "当前未配置 PALLAS_WEBUI_API_TOKEN，请先在 .env 中设置并重启 Bot。"
        error = (reason or "").strip()
        if token_submitted:
            error = "Token 无效，请重试。"
        return HTMLResponse(
            f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Pallas 控制台登录</title>
  <style>
    :root {{
      --bg0: #f2f6fc;
      --card: #ffffff;
      --bd: rgba(22, 100, 196, 0.14);
      --txt: #1f2a44;
      --muted: #5c6e8f;
      --accent: #1664c4;
      --radius: 14px;
      --font: ui-sans-serif, system-ui, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg0: #070a0f;
        --card: #121a28;
        --bd: rgba(148, 163, 184, 0.16);
        --txt: #e8edf7;
        --muted: #8b9bb8;
        --accent: #38bdf8;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: var(--font);
      background: radial-gradient(1200px 600px at 10% -10%, rgba(22,100,196,0.10), transparent), var(--bg0);
      color: var(--txt);
      display: grid;
      place-items: center;
      padding: 20px;
    }}
    .card {{
      width: min(520px, 100%);
      background: var(--card);
      border: 1px solid var(--bd);
      border-radius: var(--radius);
      padding: 22px;
      box-shadow: 0 12px 28px rgba(15, 35, 65, 0.16);
    }}
    h2 {{ margin: 0 0 8px; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.6; }}
    .msg {{ margin-top: 10px; font-size: 14px; }}
    .msg.err {{ color: #d84a4a; }}
    .msg.warn {{ color: #b45309; }}
    form {{ margin-top: 14px; display: grid; gap: 10px; }}
    .hint {{ margin-top: 8px; font-size: 13px; color: var(--muted); }}
    input {{
      width: 100%;
      border-radius: 10px;
      border: 1px solid var(--bd);
      background: transparent;
      color: var(--txt);
      padding: 11px 12px;
      font: inherit;
    }}
    button {{
      border: none;
      border-radius: 10px;
      padding: 11px 14px;
      font: inherit;
      font-weight: 600;
      color: #fff;
      background: linear-gradient(135deg, var(--accent), #2b78d6);
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <section class="card">
    <h2>Pallas 控制台登录</h2>
    <p>请输入控制台 Token 后进入 WebUI。</p>
    {'<p class="msg warn">' + html_escape(detail) + "</p>" if detail else ""}
    {'<p class="msg err">' + html_escape(error) + "</p>" if error else ""}
    <form id="loginForm" method="post" action="{base}/login">
      <input type="hidden" name="next" value="{html_escape(target, quote=True)}" />
      <input
        id="tokenInput"
        name="token"
        type="password"
        placeholder="PALLAS_WEBUI_API_TOKEN"
        autocomplete="off"
        required
      />
      <button id="submitBtn" type="submit">进入控制台</button>
    </form>
    <p class="hint">可在当前浏览器会话内临时保存 Token（关闭页面后失效）。</p>
  </section>
  <script>
    (function initLogin() {{
      const KEY = "pallas_webui_login_token_session";
      const form = document.getElementById("loginForm");
      const input = document.getElementById("tokenInput");
      const btn = document.getElementById("submitBtn");
      const saved = (sessionStorage.getItem(KEY) || "").trim();
      if (input && !input.value) input.value = saved || "";
      if (form && input) {{
        form.addEventListener("submit", () => {{
          const t = (input.value || "").trim();
          if (t) sessionStorage.setItem(KEY, t);
          if (btn) {{
            btn.textContent = "登录中...";
            btn.setAttribute("disabled", "disabled");
          }}
        }});
      }}
    }})();
  </script>
</body>
</html>"""
        )

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
        if _is_token_valid(token):
            response = RedirectResponse(url=target, status_code=303)
            response.set_cookie(
                key=page_cookie_name,
                value=token,
                httponly=True,
                samesite="lax",
                secure=request.url.scheme == "https",
                path=base or "/",
            )
            return response
        return _render_login_page(target=target, reason=None, token_submitted=True)

    @router.post(f"{base}/logout", include_in_schema=False, response_model=None)
    async def _logout() -> RedirectResponse:
        response = RedirectResponse(url=f"{base}/login", status_code=303)
        response.delete_cookie(key=page_cookie_name, path=base or "/")
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
        if not required_token:
            return _login_redirect(
                str(request.url.path),
                reason="当前未配置 PALLAS_WEBUI_API_TOKEN，请先在 .env 中设置并重启 Bot",
            )
        got = _request_token(request, token)
        if not got:
            return _login_redirect(str(request.url.path))
        if not _is_token_valid(got):
            return _login_redirect(
                str(request.url.path),
                reason="控制台 Token 不匹配，请确认与 .env 中 PALLAS_WEBUI_API_TOKEN 一致",
            )
        idx = public_dir / "index.html"
        if idx.is_file():
            response = FileResponse(idx)
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
                got = _request_token(request, token)
                if _is_token_valid(got):
                    response = FileResponse(target)
                    _refresh_page_cookie(response, request, got)
                    return response
                return _login_redirect(f"{base}/{path}", reason="请先登录后再访问页面")
            return FileResponse(target)
        fallback = _pick_index_fallback()
        if fallback is not None:
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
