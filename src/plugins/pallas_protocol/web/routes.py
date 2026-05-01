"""HTTP 路由注册：与 ``PallasProtocolService`` 通过参数注入耦合，便于测试与替换 UI。"""

from __future__ import annotations

from html import escape as html_escape
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from fastapi import FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

if TYPE_CHECKING:
    from ..config import Config
    from ..service import PallasProtocolService


def _check_pallas_protocol_token(
    plugin_config: Config,
    x_pallas_protocol_token: str | None,
    query_token: str | None,
    cookie_token: str | None = None,
) -> None:
    need = (plugin_config.pallas_protocol_token or "").strip()
    if not need:
        raise HTTPException(
            status_code=403,
            detail="pallas_protocol_token 未配置，协议端管理 API 已禁用；请在 .env 中设置 PALLAS_PROTOCOL_TOKEN 后再试",
        )
    got = (x_pallas_protocol_token or query_token or cookie_token or "").strip()
    if not got:
        raise HTTPException(
            status_code=401,
            detail="未提供协议端管理 Token",
        )
    if got != need:
        raise HTTPException(
            status_code=401,
            detail="协议端管理 Token 校验失败，请重新输入后登录",
        )


def register_pallas_protocol_routes(
    app: FastAPI,
    *,
    manager: PallasProtocolService,
    plugin_config: Config,
) -> None:
    from ..config import resolve_protocol_webui_base_path
    from .pages import (
        render_account_workspace,
        render_dashboard,
        render_import_page,
        render_new_account_page,
        render_runtime_page,
    )

    base = resolve_protocol_webui_base_path(plugin_config)
    page_cookie_name = "pallas_protocol_page_token"

    def _auth(h: str | None, q: str | None, c: str | None = None) -> None:
        _check_pallas_protocol_token(plugin_config, h, q, c)

    def _ensure_page_auth(
        *,
        request: Request,
        token: str | None,
        x_pallas_protocol_token: str | None,
        next_path: str,
    ) -> RedirectResponse | None:
        try:
            cookie_token = request.cookies.get(page_cookie_name)
            _auth(x_pallas_protocol_token, token, cookie_token)
            return None
        except HTTPException as e:
            encoded_next = quote(next_path, safe="/?=&-_.~")
            detail = str(getattr(e, "detail", "") or "鉴权失败")
            if detail == "未提供协议端管理 Token":
                return RedirectResponse(url=f"{base}/login?next={encoded_next}", status_code=307)
            reason = quote(detail, safe="")
            return RedirectResponse(url=f"{base}/login?next={encoded_next}&reason={reason}", status_code=307)

    def _resolve_login_target(next_path: str | None) -> str:
        target = (next_path or f"{base}/").strip() or f"{base}/"
        if not target.startswith(base):
            target = f"{base}/"
        return target

    def _render_login_page(*, target: str, err: str, detail: str) -> HTMLResponse:
        error_html = f"<p style='color:#c0392b;margin-top:8px'>{html_escape(err)}</p>" if err else ""
        detail_html = f"<p style='color:#8a6d3b;margin-top:8px'>{html_escape(detail)}</p>" if detail else ""
        return HTMLResponse(
            f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Pallas 协议端登录</title>
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
    <h2>Pallas 协议端登录</h2>
    <p>请输入协议端管理 Token 后进入控制台。</p>
    {detail_html.replace("<p ", "<p class='msg warn' ")}
    {error_html.replace("<p ", "<p class='msg err' ")}
    <form method="post" action="{base}/login">
      <input type="hidden" name="next" value="{html_escape(target, quote=True)}" />
      <input
        id="tokenInput"
        name="token"
        type="password"
        placeholder="PALLAS_PROTOCOL_TOKEN"
        autocomplete="off"
        required
      />
      <button id="submitBtn" type="submit">进入控制台</button>
    </form>
    <p class="hint">可在当前浏览器会话内临时保存 Token（关闭页面后失效）。</p>
  </section>
  <script>
    (function initLogin() {{
      const KEY = "pallas_protocol_token_session";
      const form = document.querySelector("form");
      const input = document.getElementById("tokenInput");
      const btn = document.getElementById("submitBtn");
      const saved = (sessionStorage.getItem(KEY) || "").trim();
      if (input && !input.value) input.value = saved;
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

    @app.get(f"{base}/login", response_class=HTMLResponse, response_model=None)
    async def napcat_login_page(
        next_path: str | None = Query(default=None, alias="next"),
        reason: str | None = Query(default=None),
    ):
        target = _resolve_login_target(next_path)
        err = ""
        default_reason = (reason or "").strip()
        if default_reason:
            err = default_reason
        detail = ""
        if not (plugin_config.pallas_protocol_token or "").strip():
            detail = "当前未配置 PALLAS_PROTOCOL_TOKEN，请先在 .env 中设置并重启 Bot。"
        return _render_login_page(target=target, err=err, detail=detail)

    @app.post(f"{base}/login", response_class=HTMLResponse, response_model=None)
    async def napcat_login_submit(
        request: Request,
        next_path: str | None = Form(default=None, alias="next"),
        token: str = Form(...),
    ) -> RedirectResponse | HTMLResponse:
        target = _resolve_login_target(next_path)
        detail = ""
        if not (plugin_config.pallas_protocol_token or "").strip():
            detail = "当前未配置 PALLAS_PROTOCOL_TOKEN，请先在 .env 中设置并重启 Bot。"
        try:
            _auth(None, token)
        except HTTPException as e:
            return _render_login_page(
                target=target,
                err=str(getattr(e, "detail", "") or "Token 校验失败"),
                detail=detail,
            )
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

    @app.post(f"{base}/logout", response_model=None)
    async def napcat_logout() -> RedirectResponse:
        response = RedirectResponse(url=f"{base}/login", status_code=303)
        response.delete_cookie(key=page_cookie_name, path=base or "/")
        return response

    @app.get(base, response_class=HTMLResponse)
    @app.get(f"{base}/", response_class=HTMLResponse)
    async def napcat_dashboard(
        request: Request,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        redirect = _ensure_page_auth(
            request=request,
            token=token,
            x_pallas_protocol_token=x_pallas_protocol_token,
            next_path=str(request.url.path),
        )
        if redirect is not None:
            return redirect
        return HTMLResponse(render_dashboard(resolve_protocol_webui_base_path(plugin_config)))

    @app.get(f"{base}/new", response_class=HTMLResponse)
    async def napcat_new_account(
        request: Request,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        redirect = _ensure_page_auth(
            request=request,
            token=token,
            x_pallas_protocol_token=x_pallas_protocol_token,
            next_path=str(request.url.path),
        )
        if redirect is not None:
            return redirect
        return HTMLResponse(render_new_account_page(resolve_protocol_webui_base_path(plugin_config)))

    @app.get(f"{base}/import", response_class=HTMLResponse)
    async def napcat_import_page(
        request: Request,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        redirect = _ensure_page_auth(
            request=request,
            token=token,
            x_pallas_protocol_token=x_pallas_protocol_token,
            next_path=str(request.url.path),
        )
        if redirect is not None:
            return redirect
        return HTMLResponse(render_import_page(resolve_protocol_webui_base_path(plugin_config)))

    @app.post(f"{base}/api/accounts/import")
    async def import_accounts(
        payload: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        import asyncio
        from pathlib import Path

        from ..importer import run_import

        source_dir = Path(str(payload.get("source_dir", "")).strip())
        if not await asyncio.to_thread(source_dir.is_dir):
            raise HTTPException(status_code=400, detail=f"目录不存在: {source_dir}")
        dry_run = bool(payload.get("dry_run", False))
        skip_existing = bool(payload.get("skip_existing", True))
        ws_url = str(payload.get("ws_url", "") or "").strip()
        ws_token = str(payload.get("ws_token", "") or "")
        ws_name = str(payload.get("ws_name", "") or "pallas").strip() or "pallas"

        existing = {acc["id"]: acc for acc in manager.list_accounts()}
        result, new_accounts = run_import(
            source_dir,
            existing,
            dry_run=dry_run,
            skip_existing=skip_existing,
            ws_url=ws_url,
            ws_name=ws_name,
            ws_token=ws_token,
            instances_root=manager._instances_root,
        )
        if not dry_run and result.imported:
            manager.bulk_register(new_accounts)
        return {
            "imported": result.imported,
            "skipped": result.skipped,
            "failed": result.failed,
        }

    @app.get(f"{base}/runtime", response_class=HTMLResponse)
    async def napcat_runtime_page(
        request: Request,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        redirect = _ensure_page_auth(
            request=request,
            token=token,
            x_pallas_protocol_token=x_pallas_protocol_token,
            next_path=str(request.url.path),
        )
        if redirect is not None:
            return redirect
        return HTMLResponse(render_runtime_page(resolve_protocol_webui_base_path(plugin_config)))

    @app.get(f"{base}/account/{{account_id}}/edit")
    async def napcat_edit_redirect(
        account_id: str,
        request: Request,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        """旧书签 ``…/edit`` → 账号子路径设置页。"""
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        redirect = _ensure_page_auth(
            request=request,
            token=token,
            x_pallas_protocol_token=x_pallas_protocol_token,
            next_path=str(request.url.path),
        )
        if redirect is not None:
            return redirect
        if not manager.has_account(account_id):
            raise HTTPException(status_code=404, detail="账号不存在")
        q = "tab=settings"
        aid = quote(str(account_id), safe="")
        return RedirectResponse(url=f"{base}/account/{aid}?{q}", status_code=307)

    @app.get(f"{base}/account/{{account_id}}", response_class=HTMLResponse)
    async def napcat_account_workspace(
        account_id: str,
        request: Request,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        redirect = _ensure_page_auth(
            request=request,
            token=token,
            x_pallas_protocol_token=x_pallas_protocol_token,
            next_path=str(request.url.path),
        )
        if redirect is not None:
            return redirect
        if not manager.has_account(account_id):
            raise HTTPException(status_code=404, detail="账号不存在")
        return HTMLResponse(render_account_workspace(resolve_protocol_webui_base_path(plugin_config), account_id))

    @app.get(f"{base}/api/runtime")
    async def runtime_status(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        return manager.runtime_overview()

    @app.get(f"{base}/api/connection-hints")
    async def connection_hints(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        return manager.connection_hints()

    @app.get(f"{base}/api/nonebot-logs")
    async def nonebot_log_tail(
        lines: int = Query(default=400, ge=1, le=2000),
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        from src.common.web import tail_nonebot_log_lines

        return {"logs": tail_nonebot_log_lines(lines)}

    @app.post(f"{base}/api/runtime/download")
    async def runtime_download(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
        tag: str | None = Query(default=None),
        target_platform: str | None = Query(default=None),
        runtime_mode: str | None = Query(default=None),
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            return manager.start_runtime_download(
                tag=tag or None,
                target_platform=target_platform or None,
                runtime_mode=runtime_mode or None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.get(f"{base}/api/runtime/profile")
    async def runtime_profile(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        return {"profile": manager.runtime_profile()}

    @app.put(f"{base}/api/runtime/profile")
    async def update_runtime_profile(
        payload: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            return {"profile": manager.update_runtime_profile(payload)}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post(f"{base}/api/runtime/docker/pull")
    async def runtime_docker_pull(
        payload: dict[str, Any] | None = None,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        image = ""
        if isinstance(payload, dict):
            image = str(payload.get("image", "") or "").strip()
        return await manager.pull_docker_image(image or None)

    @app.get(f"{base}/api/runtime/docker/images")
    async def runtime_docker_images(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        return await manager.list_local_docker_images()

    @app.post(f"{base}/api/runtime/docker/stop-all")
    async def runtime_docker_stop_all(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        return await manager.stop_all_labeled_docker_containers()

    @app.post(f"{base}/api/runtime/docker/prune-stopped")
    async def runtime_docker_prune_stopped(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        return await manager.prune_stopped_labeled_docker_containers()

    @app.get(f"{base}/api/runtime/releases")
    async def runtime_releases(
        limit: int = Query(default=10, ge=1, le=200),
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        releases = await manager.fetch_runtime_releases(limit=limit)
        return {"releases": releases}

    @app.post(f"{base}/api/runtime/rescan")
    async def runtime_rescan(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        return manager.rescan_runtime_extract()

    @app.get(f"{base}/api/accounts")
    async def list_accounts(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        return {"accounts": manager.list_accounts()}

    @app.get(f"{base}/api/accounts/{{account_id}}")
    async def get_one_account(
        account_id: str,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        acc = manager.get_account(account_id)
        if acc is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        return {"account": acc}

    @app.post(f"{base}/api/accounts")
    async def create_account(
        payload: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            account = manager.create_account(payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"account": account}

    @app.put(f"{base}/api/accounts/{{account_id}}")
    async def update_account(
        account_id: str,
        payload: dict[str, Any],
        restart: bool = Query(default=True),
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            result = await manager.update_account(account_id, payload, restart=restart)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except (RuntimeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return result

    @app.delete(f"{base}/api/accounts/{{account_id}}")
    async def delete_account(
        account_id: str,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            await manager.delete_account(account_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"ok": True}

    @app.post(f"{base}/api/accounts/{{account_id}}/start")
    async def start_account(
        account_id: str,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            account = await manager.start_account(account_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"account": account}

    @app.post(f"{base}/api/accounts/{{account_id}}/stop")
    async def stop_account(
        account_id: str,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        account = await manager.stop_account(account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        return {"account": account}

    @app.post(f"{base}/api/accounts/{{account_id}}/restart")
    async def restart_account(
        account_id: str,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            account = await manager.restart_account(account_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"account": account}

    @app.get(f"{base}/api/accounts/{{account_id}}/logs")
    async def account_logs(
        account_id: str,
        lines: int = Query(default=200, ge=1, le=2000),
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        if not manager.has_account(account_id):
            raise HTTPException(status_code=404, detail="账号不存在")
        await manager.ensure_docker_logs_if_needed(account_id)
        return {"logs": manager.tail_logs(account_id, lines=lines)}

    @app.get(f"{base}/api/accounts/{{account_id}}/configs")
    async def get_account_configs(
        account_id: str,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            return manager.get_account_configs(account_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.put(f"{base}/api/accounts/{{account_id}}/configs")
    async def update_account_configs(
        account_id: str,
        payload: dict[str, Any],
        restart: bool = Query(default=True),
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            return await manager.update_account_configs(account_id, payload, restart=restart)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
