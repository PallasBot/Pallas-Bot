"""HTTP 路由注册：与 ``PallasProtocolService`` 通过参数注入耦合，便于测试与替换 UI。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

if TYPE_CHECKING:
    from ..config import Config
    from ..service import PallasProtocolService


def _check_pallas_protocol_token(
    plugin_config: Config,
    x_pallas_protocol_token: str | None,
    query_token: str | None,
) -> None:
    need = (plugin_config.pallas_protocol_token or "").strip()
    if not need:
        return
    got = (x_pallas_protocol_token or query_token or "").strip()
    if got != need:
        raise HTTPException(status_code=401, detail="Invalid token")


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

    def _auth(h: str | None, q: str | None) -> None:
        _check_pallas_protocol_token(plugin_config, h, q)

    @app.get(base, response_class=HTMLResponse)
    @app.get(f"{base}/", response_class=HTMLResponse)
    async def napcat_dashboard(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        _auth(x_pallas_protocol_token, token)
        return HTMLResponse(render_dashboard(resolve_protocol_webui_base_path(plugin_config)))

    @app.get(f"{base}/new", response_class=HTMLResponse)
    async def napcat_new_account(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        _auth(x_pallas_protocol_token, token)
        return HTMLResponse(render_new_account_page(resolve_protocol_webui_base_path(plugin_config)))

    @app.get(f"{base}/import", response_class=HTMLResponse)
    async def napcat_import_page(
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        _auth(x_pallas_protocol_token, token)
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
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        _auth(x_pallas_protocol_token, token)
        return HTMLResponse(render_runtime_page(resolve_protocol_webui_base_path(plugin_config)))

    @app.get(f"{base}/account/{{account_id}}/edit")
    async def napcat_edit_redirect(
        account_id: str,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        """旧书签 ``…/edit`` → 账号子路径设置页。"""
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        _auth(x_pallas_protocol_token, token)
        if not manager.has_account(account_id):
            raise HTTPException(status_code=404, detail="账号不存在")
        q = "tab=settings"
        if (token or "").strip():
            q += "&token=" + quote((token or "").strip(), safe="")
        aid = quote(str(account_id), safe="")
        return RedirectResponse(url=f"{base}/account/{aid}?{q}", status_code=307)

    @app.get(f"{base}/account/{{account_id}}", response_class=HTMLResponse)
    async def napcat_account_workspace(
        account_id: str,
        token: str | None = Query(default=None),
        x_pallas_protocol_token: str | None = Header(default=None, alias="X-Pallas-Protocol-Token"),
    ):
        if not plugin_config.pallas_protocol_webui_enabled:
            raise HTTPException(status_code=404, detail="Pallas 协议端管理页已关闭")
        _auth(x_pallas_protocol_token, token)
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
    ):
        _auth(x_pallas_protocol_token, token)
        try:
            return manager.start_runtime_download()
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

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
