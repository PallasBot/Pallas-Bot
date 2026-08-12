"""Pallas-Bot WebUI console API: auth login/setup and security."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from nonebot.log import logger
from pydantic import BaseModel, ConfigDict, Field

from packages.pb_webui.console_openapi_models import _ApiOkResponse
from pallas.console.webui.console_login import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SEC,
    mint_session_token,
    set_shared_console_login_token,
    verify_console_password,
)

from .console_read_cache import clear_extended_read_cache
from .extended_common import (
    build_console_openapi_schema,
    check_pallas_write_token,
)

if TYPE_CHECKING:
    from .config import Config


class _ConsoleSetupStatusData(BaseModel):
    auth_configured: bool
    setup_completed: bool
    default_password_active: bool
    requires_setup: bool
    first_completed_at: str | None = None
    updated_at: str | None = None


class _ConsoleLoginChangeData(BaseModel):
    message: str


class _AuthLoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=512)


class ChangeConsoleLoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=1, max_length=256)


def register_auth_security_router(
    router: APIRouter,
    router_pub: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    app: Any,
) -> None:
    """Register auth and security routes."""

    @router_pub.post(f"{x}/auth/login", include_in_schema=False)
    async def _auth_login(
        request: Request,
        body: Annotated[_AuthLoginBody, Body()],
    ) -> JSONResponse:
        client = getattr(request, "client", None)
        ip = getattr(client, "host", "?") if client is not None else "?"
        if not verify_console_password(body.password):
            logger.warning("控制台登录失败，来源 ip [{}]", ip)
            raise HTTPException(status_code=401, detail="密码错误")
        logger.info("控制台登录成功，来源 ip [{}]", ip)
        tok = mint_session_token()
        resp = JSONResponse({"ok": True, "data": {"token": tok}})
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=tok,
            max_age=SESSION_TTL_SEC,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )
        clear_extended_read_cache()
        return resp

    @router_pub.get(
        f"{x}/auth/setup-status",
        include_in_schema=True,
        response_model=_ApiOkResponse[_ConsoleSetupStatusData],
    )
    async def _auth_setup_status() -> dict[str, Any]:
        from packages.pb_webui import extended_api as ext

        return {"ok": True, "data": ext.console_setup_status()}

    @router_pub.get(f"{x}/openapi.json", include_in_schema=False)
    async def _console_openapi_json() -> JSONResponse:
        return JSONResponse(build_console_openapi_schema(app, api_base=x))

    @router.post(
        f"{x}/security/console-login",
        include_in_schema=True,
        response_model=_ApiOkResponse[_ConsoleLoginChangeData],
    )
    async def _security_console_login(
        body: ChangeConsoleLoginBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> dict[str, Any]:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            set_shared_console_login_token(body.new_password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        logger.info("控制台密钥已修改")
        return {"ok": True, "data": {"message": "已保存"}}
