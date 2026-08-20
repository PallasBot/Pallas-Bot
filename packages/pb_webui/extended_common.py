"""Shared helpers for Pallas-Bot console extended API domains."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.openapi.utils import get_openapi
from nonebot.log import logger
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from pallas.console.webui.console_login import (
    current_http_request,
    extract_session_from_request,
    is_console_auth_configured,
)
from pallas.core.foundation.bot_version import get_pallas_bot_version_for_health
from pallas.core.foundation.logging.throttle import log_rate_limited
from pallas.core.platform.shard import context as shard_ctx


def shard_hub_console() -> bool:
    return shard_ctx.sharding_active() and shard_ctx.is_hub()


def shard_worker_console() -> bool:
    return shard_ctx.sharding_active() and shard_ctx.is_worker()


def build_console_openapi_schema(app: Any, *, api_base: str) -> dict[str, Any]:
    """导出仅包含控制台 API 前缀的 OpenAPI schema。"""
    x = (api_base or "/pallas/api").strip()
    if not x.startswith("/"):
        x = "/" + x
    x = x.rstrip("/")
    schema = get_openapi(
        title="Pallas-Bot 控制台 API",
        version=get_pallas_bot_version_for_health(),
        routes=app.routes,
    )
    schema["paths"] = {
        path: item for path, item in (schema.get("paths") or {}).items() if str(path).startswith(f"{x}/")
    }
    schema["info"] = {
        **dict(schema.get("info") or {}),
        "title": "Pallas-Bot 控制台 API",
        "version": get_pallas_bot_version_for_health(),
        "description": "仅包含控制台 API 前缀下的接口。",
    }
    schema["servers"] = [{"url": x}]
    return schema


# 审批写操作后：好友/群 OneBot 列表与按 Bot 群配置合并视图一并失效
CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES: tuple[str, ...] = (
    "friend_requests",
    "request_overview",
    "friend_list:",
    "group_list:",
    "group_configs_bot:",
)


def jsonable_value(v: Any) -> Any:
    if v is PydanticUndefined:
        return None
    if isinstance(v, BaseModel):
        return v.model_dump(mode="python")
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, dict):
        return {str(k): jsonable_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [jsonable_value(x) for x in v]
    if isinstance(v, (set, tuple)):
        return [jsonable_value(x) for x in v]
    return v


def require_pallas_token_configured(
    plugin_config: Any,
    *,
    x_pallas_token: str | None,
    token: str | None,
    x_pallas_api_key: str | None = None,
) -> None:
    """所有控制台 API 共享的鉴权入口：与协议端共用会话，或按长期 API Key 放行。"""
    if bool(getattr(plugin_config, "pallas_webui_dev_mode", False)):
        return
    req = current_http_request()
    if req is None:
        raise HTTPException(status_code=500, detail="控制台鉴权缺少请求上下文")
    cookies = dict(req.cookies)
    if extract_session_from_request(
        cookies=cookies,
        header_token=x_pallas_token,
        query_token=token,
        cookie_token=None,
        api_key=x_pallas_api_key,
    ):
        return
    if not is_console_auth_configured():
        raise HTTPException(
            status_code=503,
            detail="统一控制台鉴权未初始化，请检查 data/pallas_console/",
        )
    client = getattr(req, "client", None)
    ip = getattr(client, "host", "?") if client is not None else "?"
    log_rate_limited(
        logger,
        "warning",
        "console.auth.401",
        "控制台鉴权失败，path [{}]、ip [{}]",
        getattr(req, "url", "") or "?",
        ip,
    )
    raise HTTPException(status_code=401, detail="Invalid token")


# 历史调用点保留同名别名；运行时委托 extended_api 以便测试 monkeypatch。
def check_pallas_write_token(
    plugin_config: Any,
    *,
    x_pallas_token: str | None,
    token: str | None,
) -> None:
    from packages.pb_webui import extended_api as ext

    fn = getattr(ext, "_check_pallas_write_token", require_pallas_token_configured)
    return fn(plugin_config, x_pallas_token=x_pallas_token, token=token)
