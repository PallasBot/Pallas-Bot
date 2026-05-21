"""分片 hub：挂载 MAA HTTP 转发路由（worker 仍保留本机真实处理）。"""

from __future__ import annotations

from fastapi import FastAPI, Request  # noqa: TC002
from fastapi.responses import JSONResponse
from nonebot import logger

from src.common.shard.coord.maa_http_forward import forward_maa_json_post

_mounted_paths: frozenset[str] = frozenset()


def _maa_http_paths() -> tuple[str, str]:
    from src.plugins.maa.config import get_maa_config
    from src.plugins.maa.endpoints import normalize_http_path

    cfg = get_maa_config()
    return (
        normalize_http_path(cfg.maa_get_task_path),
        normalize_http_path(cfg.maa_report_status_path),
    )


async def hub_maa_get_task(request: Request) -> JSONResponse:
    get_path, _ = _maa_http_paths()
    body = await request.json()
    if not isinstance(body, dict):
        body = {}
    user = str(body.get("user") or "")
    status, payload = await forward_maa_json_post(user, get_path, body)
    if payload is None:
        return JSONResponse(content={"tasks": []}, status_code=200)
    if status >= 400:
        return JSONResponse(content=payload if isinstance(payload, dict) else {"tasks": []}, status_code=status)
    return JSONResponse(content=payload, status_code=status)


async def hub_maa_report_status(request: Request) -> JSONResponse:
    _, report_path = _maa_http_paths()
    body = await request.json()
    if not isinstance(body, dict):
        body = {}
    user = str(body.get("user") or "")
    status, payload = await forward_maa_json_post(user, report_path, body)
    if payload is None:
        return JSONResponse(content={"message": "ok"}, status_code=200)
    if status >= 400:
        return JSONResponse(
            content=payload if isinstance(payload, dict) else {"message": "ok"},
            status_code=status,
        )
    return JSONResponse(content=payload, status_code=status)


def remount_maa_hub_forward_routes(app: FastAPI) -> None:
    global _mounted_paths
    get_path, report_path = _maa_http_paths()
    new_paths = frozenset({get_path, report_path})
    if new_paths == _mounted_paths:
        return

    if _mounted_paths:
        app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) not in _mounted_paths]

    app.add_api_route(get_path, hub_maa_get_task, methods=["POST"], name="maa_hub_get_task")
    app.add_api_route(report_path, hub_maa_report_status, methods=["POST"], name="maa_hub_report_status")
    _mounted_paths = new_paths
    logger.info("maa hub forward routes remounted: getTask={} reportStatus={}", get_path, report_path)
